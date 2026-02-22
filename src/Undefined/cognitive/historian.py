"""后台史官 Worker，轮询队列处理任务。"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime
from typing import Any, Callable

logger = logging.getLogger(__name__)

_PRONOUN_RE = re.compile(
    r"(?<![a-zA-Z])(我|你|他|她|它|他们|她们|它们|这位|那位)(?![a-zA-Z])"
)
_REL_TIME_RE = re.compile(r"(今天|昨天|明天|刚才|刚刚|稍后|上周|下周|最近)")
_REL_PLACE_RE = re.compile(r"(这里|那边|本地|当地|这儿|那儿)")
_MAX_LOG_PREVIEW_LEN = 200
_MAX_HIT_VALUES_PER_PATTERN = 5

_REWRITE_TOOL = {
    "type": "function",
    "function": {
        "name": "submit_rewrite",
        "description": "提交绝对化改写后的事件文本",
        "parameters": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "改写后的纯文本"},
            },
            "required": ["text"],
        },
    },
}

_PROFILE_TOOL = {
    "type": "function",
    "function": {
        "name": "update_profile",
        "description": "更新用户/群侧写",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "用户/群名称"},
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "兴趣/技能标签",
                },
                "summary": {"type": "string", "description": "侧写正文（Markdown）"},
            },
            "required": ["name", "tags", "summary"],
        },
    },
}


def _preview_text(text: str, max_len: int = _MAX_LOG_PREVIEW_LEN) -> str:
    compact = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(compact) <= max_len:
        return compact
    return f"{compact[:max_len]}..."


def _collect_unique_hits(
    pattern: re.Pattern[str], text: str, *, limit: int = _MAX_HIT_VALUES_PER_PATTERN
) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for match in pattern.finditer(text):
        value = match.group(0)
        if value in seen:
            continue
        seen.add(value)
        found.append(value)
        if len(found) >= limit:
            break
    return found


class HistorianWorker:
    def __init__(
        self,
        job_queue: Any,
        vector_store: Any,
        profile_storage: Any,
        ai_client: Any,
        config_getter: Callable[[], Any],
        model_config: Any = None,
    ) -> None:
        self._job_queue = job_queue
        self._vector_store = vector_store
        self._profile_storage = profile_storage
        self._ai_client = ai_client
        self._config_getter = config_getter
        self._model_config = model_config
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        logger.info("[史官] Worker 启动中")
        self._task = asyncio.create_task(self._poll_loop())
        logger.info("[史官] Worker 已启动")

    async def stop(self) -> None:
        logger.info("[史官] Worker 停止中")
        self._stop_event.set()
        if self._task:
            await self._task
        logger.info("[史官] Worker 已停止")

    async def _poll_loop(self) -> None:
        poll_count = 0
        logger.info("[史官] 轮询循环已开始")
        while not self._stop_event.is_set():
            result = await self._job_queue.dequeue()
            if result:
                job_id, job = result
                try:
                    await self._process_job(job_id, job)
                except Exception as e:
                    retry_count = job.get("_retry_count", 0)
                    max_retries = self._config_getter().job_max_retries
                    if retry_count < max_retries:
                        logger.warning(
                            "[史官] 任务 %s 处理失败 (%s/%s)，将自动重试: %s",
                            job_id,
                            retry_count + 1,
                            max_retries,
                            e,
                        )
                        await self._job_queue.requeue(job_id, str(e))
                    else:
                        logger.error(
                            "[史官] 任务 %s 达到最大重试次数 (%s)，移入 failed: %s",
                            job_id,
                            max_retries,
                            e,
                        )
                        await self._job_queue.fail(job_id, str(e))

            poll_count += 1
            config = self._config_getter()
            if (
                config.failed_cleanup_interval > 0
                and poll_count % config.failed_cleanup_interval == 0
            ):
                from Undefined.utils.cache import cleanup_cache_dir

                cleanup_cache_dir(
                    self._job_queue._failed_dir,
                    max_age_seconds=config.failed_max_age_days * 86400,
                    max_files=config.failed_max_files,
                )
                logger.info(
                    "[史官] failed 队列清理已执行: interval=%s max_age_days=%s max_files=%s",
                    config.failed_cleanup_interval,
                    config.failed_max_age_days,
                    config.failed_max_files,
                )

            await asyncio.sleep(config.poll_interval_seconds)
        logger.info("[史官] 轮询循环已结束")

    async def _process_job(self, job_id: str, job: dict[str, Any]) -> None:
        config = self._config_getter()
        logger.info(
            "[史官] 开始处理任务 %s: user=%s group=%s sender=%s has_new_info=%s rewrite_max_retry=%s",
            job_id,
            job.get("user_id", ""),
            job.get("group_id", ""),
            job.get("sender_id", ""),
            job.get("has_new_info", False),
            config.rewrite_max_retry,
        )
        canonical = await self._rewrite(job, job_id=job_id, attempt=1)

        is_absolute = True
        for attempt in range(config.rewrite_max_retry + 1):
            hit_detail = self._collect_regex_hits(canonical)
            if not any(hit_detail.values()):
                break
            if attempt < config.rewrite_max_retry:
                logger.warning(
                    "[史官] 任务 %s 绝对化闸门命中 (%s/%s): pronoun=%s rel_time=%s rel_place=%s preview=%s",
                    job_id,
                    attempt + 1,
                    config.rewrite_max_retry + 1,
                    hit_detail["pronoun"],
                    hit_detail["relative_time"],
                    hit_detail["relative_place"],
                    _preview_text(canonical),
                )
                canonical = await self._rewrite(job, job_id=job_id, attempt=attempt + 2)
            else:
                is_absolute = False
                logger.warning(
                    "[史官] 任务 %s 绝对化失败，降级写入: final_hits=%s preview=%s",
                    job_id,
                    hit_detail,
                    _preview_text(canonical),
                )

        metadata: dict[str, Any] = {
            "user_id": job.get("user_id", ""),
            "group_id": job.get("group_id", ""),
            "sender_id": job.get("sender_id", ""),
            "request_type": job.get("request_type", ""),
            "timestamp_utc": job.get("timestamp_utc", ""),
            "timestamp_local": job.get("timestamp_local", ""),
            "is_absolute": is_absolute,
        }
        await self._vector_store.upsert_event(job_id, canonical, metadata)
        logger.info(
            "[史官] 任务 %s 事件入库完成: is_absolute=%s canonical_len=%s",
            job_id,
            is_absolute,
            len(canonical),
        )

        if job.get("has_new_info"):
            await self._merge_profile(job, canonical, job_id)

        await self._job_queue.complete(job_id)
        logger.info("[史官] 任务 %s 处理完成", job_id)

    def _check_regex(self, text: str) -> bool:
        return any(self._collect_regex_hits(text).values())

    def _collect_regex_hits(self, text: str) -> dict[str, list[str]]:
        content = str(text or "")
        return {
            "pronoun": _collect_unique_hits(_PRONOUN_RE, content),
            "relative_time": _collect_unique_hits(_REL_TIME_RE, content),
            "relative_place": _collect_unique_hits(_REL_PLACE_RE, content),
        }

    async def _rewrite(
        self, job: dict[str, Any], *, job_id: str = "", attempt: int = 1
    ) -> str:
        from Undefined.utils.resources import read_text_resource

        action_summary = str(job.get("action_summary", ""))
        new_info = str(job.get("new_info", ""))
        logger.debug(
            "[史官] 任务 %s 发起绝对化改写: attempt=%s action_len=%s new_info_len=%s",
            job_id or "unknown",
            attempt,
            len(action_summary),
            len(new_info),
        )

        template = read_text_resource("res/prompts/historian_rewrite.md")
        prompt = template.format(
            timestamp_local=job.get("timestamp_local", ""),
            timezone=job.get("timezone", "Asia/Shanghai"),
            user_id=job.get("user_id", ""),
            group_id=job.get("group_id", ""),
            sender_id=job.get("sender_id", ""),
            action_summary=action_summary,
            new_info=new_info,
        )
        response = await self._ai_client.submit_background_llm_call(
            model_config=self._model_config or self._ai_client.agent_config,
            messages=[{"role": "user", "content": prompt}],
            tools=[_REWRITE_TOOL],
            tool_choice={"type": "function", "function": {"name": "submit_rewrite"}},
            call_type="historian_rewrite",
        )
        choices = response.get("choices")
        if not isinstance(choices, list) or not choices:
            logger.error(
                "[史官] 任务 %s 改写响应缺少 choices: response_type=%s",
                job_id or "unknown",
                type(response).__name__,
            )
            raise ValueError("historian_rewrite 响应缺少 choices")

        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        if not isinstance(message, dict):
            logger.error("[史官] 任务 %s 改写响应缺少 message", job_id or "unknown")
            raise ValueError("historian_rewrite 响应缺少 message")

        tool_calls = message.get("tool_calls")
        if not isinstance(tool_calls, list) or not tool_calls:
            logger.error(
                "[史官] 任务 %s 改写响应缺少 tool_calls: content_preview=%s",
                job_id or "unknown",
                _preview_text(str(message.get("content", ""))),
            )
            raise ValueError("historian_rewrite 响应缺少 tool_calls")

        tool_call = tool_calls[0]
        raw_args = str(
            tool_call.get("function", {}).get("arguments", "{}")
            if isinstance(tool_call, dict)
            else "{}"
        )
        try:
            args = json.loads(raw_args)
        except json.JSONDecodeError as exc:
            logger.error(
                "[史官] 任务 %s 改写工具参数 JSON 解析失败: attempt=%s err=%s raw_preview=%s",
                job_id or "unknown",
                attempt,
                exc,
                _preview_text(raw_args),
            )
            raise

        text = str(args.get("text", "")).strip()
        logger.debug(
            "[史官] 任务 %s 收到改写候选: attempt=%s len=%s preview=%s",
            job_id or "unknown",
            attempt,
            len(text),
            _preview_text(text),
        )
        return text

    async def _merge_profile(
        self, job: dict[str, Any], canonical: str, event_id: str
    ) -> None:
        import yaml

        entity_type = "group" if job.get("group_id") else "user"
        entity_id = str(
            job.get("group_id") or job.get("user_id") or job.get("sender_id", "")
        )
        if not entity_id:
            logger.warning("[史官] 任务 %s 侧写合并跳过：缺少实体ID", event_id)
            return
        logger.info(
            "[史官] 任务 %s 开始合并侧写: entity_type=%s entity_id=%s",
            event_id,
            entity_type,
            entity_id,
        )

        current = (
            await self._profile_storage.read_profile(entity_type, entity_id)
            or "（暂无侧写）"
        )

        from Undefined.utils.resources import read_text_resource

        template = read_text_resource("res/prompts/historian_profile_merge.md")
        prompt = template.format(
            current_profile=current,
            canonical_text=canonical,
            new_info=job.get("new_info", ""),
        )

        response = await self._ai_client.submit_background_llm_call(
            model_config=self._model_config or self._ai_client.agent_config,
            messages=[{"role": "user", "content": prompt}],
            tools=[_PROFILE_TOOL],
            tool_choice={"type": "function", "function": {"name": "update_profile"}},
            call_type="historian_profile_merge",
        )

        choices = response.get("choices")
        if not isinstance(choices, list) or not choices:
            logger.error("[史官] 任务 %s 侧写合并响应缺少 choices", event_id)
            raise ValueError("historian_profile_merge 响应缺少 choices")
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        if not isinstance(message, dict):
            logger.error("[史官] 任务 %s 侧写合并响应缺少 message", event_id)
            raise ValueError("historian_profile_merge 响应缺少 message")
        tool_calls = message.get("tool_calls")
        if not isinstance(tool_calls, list) or not tool_calls:
            logger.error(
                "[史官] 任务 %s 侧写合并响应缺少 tool_calls: content_preview=%s",
                event_id,
                _preview_text(str(message.get("content", ""))),
            )
            raise ValueError("historian_profile_merge 响应缺少 tool_calls")
        tool_call = tool_calls[0]
        raw_args = str(
            tool_call.get("function", {}).get("arguments", "{}")
            if isinstance(tool_call, dict)
            else "{}"
        )
        try:
            args = json.loads(raw_args)
        except json.JSONDecodeError as exc:
            logger.error(
                "[史官] 任务 %s 侧写合并工具参数 JSON 解析失败: err=%s raw_preview=%s",
                event_id,
                exc,
                _preview_text(raw_args),
            )
            raise

        frontmatter = {
            "entity_type": entity_type,
            "entity_id": entity_id,
            "name": args.get("name", ""),
            "tags": args.get("tags", []),
            "updated_at": datetime.now().isoformat(),
            "source_event_id": event_id,
        }
        content = f"---\n{yaml.dump(frontmatter, allow_unicode=True)}---\n{args.get('summary', '')}"

        await self._profile_storage.write_profile(entity_type, entity_id, content)
        logger.info(
            "[史官] 任务 %s 侧写文件写入完成: entity_type=%s entity_id=%s tags=%s",
            event_id,
            entity_type,
            entity_id,
            args.get("tags", []),
        )
        await self._vector_store.upsert_profile(
            f"{entity_type}:{entity_id}",
            args.get("summary", ""),
            {
                "entity_type": entity_type,
                "entity_id": entity_id,
                "name": args.get("name", ""),
            },
        )
        logger.info(
            "[史官] 任务 %s 侧写向量入库完成: profile_id=%s",
            event_id,
            f"{entity_type}:{entity_id}",
        )
