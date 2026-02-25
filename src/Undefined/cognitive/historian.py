"""后台史官 Worker，轮询队列处理任务。"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Callable

logger = logging.getLogger(__name__)

_PRONOUN_RE = re.compile(
    r"(?<![a-zA-Z])(我|你|他|她|它|他们|她们|它们|这位|那位)(?![a-zA-Z])"
)
_REL_TIME_RE = re.compile(r"(今天|昨天|明天|刚才|刚刚|稍后|上周|下周|最近)")
_REL_PLACE_RE = re.compile(r"(这里|那边|本地|当地|这儿|那儿)")
_ID_RE = re.compile(r"(?<!\d)(\d{5,12})(?!\d)")
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
                "skip": {
                    "type": "boolean",
                    "description": "是否跳过更新；当新信息不稳定/不足时为 true",
                },
                "skip_reason": {
                    "type": "string",
                    "description": "跳过原因",
                },
                "name": {"type": "string", "description": "用户/群名称"},
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "maxItems": 10,
                    "description": "身份级标签（角色/核心领域），最多 10 个，不写话题",
                },
                "summary": {"type": "string", "description": "侧写正文（Markdown）"},
            },
            "required": ["skip", "name", "tags", "summary"],
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


def _collect_unique_id_hits(
    text: str, *, limit: int = _MAX_HIT_VALUES_PER_PATTERN
) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for match in _ID_RE.finditer(str(text or "")):
        value = match.group(1)
        if value in seen:
            continue
        seen.add(value)
        found.append(value)
        if len(found) >= limit:
            break
    return found


def _extract_frontmatter_name(markdown: str) -> str:
    text = str(markdown or "")
    if not text.startswith("---"):
        return ""
    try:
        import yaml

        parts = text[3:].split("---", 1)
        if len(parts) != 2:
            return ""
        frontmatter = yaml.safe_load(parts[0])
        if not isinstance(frontmatter, dict):
            return ""
        value = frontmatter.get("name")
        return str(value).strip() if value is not None else ""
    except Exception:
        return ""


def _escape_braces(text: str) -> str:
    value = str(text or "")
    return value.replace("{", "{{").replace("}", "}}")


def _resolve_timestamp_epoch(job: dict[str, Any]) -> int:
    raw_epoch = job.get("timestamp_epoch")
    if isinstance(raw_epoch, (int, float)):
        return int(raw_epoch)
    if isinstance(raw_epoch, str):
        try:
            return int(float(raw_epoch.strip()))
        except Exception:
            pass

    for key in ("timestamp_utc", "timestamp_local"):
        raw_value = job.get(key)
        if not isinstance(raw_value, str):
            continue
        text = raw_value.strip()
        if not text:
            continue
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return int(parsed.timestamp())
        except Exception:
            continue

    return int(datetime.now(timezone.utc).timestamp())


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "y", "on"}:
            return True
        if normalized in {"0", "false", "no", "n", "off", ""}:
            return False
    return False


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

    async def _rewrite_and_validate(
        self, job: dict[str, Any], job_id: str
    ) -> tuple[str, bool]:
        """改写并验证绝对化，返回 (canonical, is_absolute)。"""
        config = self._config_getter()
        canonical = await self._rewrite(job, job_id=job_id, attempt=1)
        is_absolute = True
        force_gate_bypass = _coerce_bool(job.get("force", False))
        must_keep_ids = self._collect_source_entity_ids(job)
        for attempt in range(config.rewrite_max_retry + 1):
            hit_detail = self._collect_regex_hits(canonical)
            has_regex_hits = any(hit_detail.values())
            entity_drift_ids = self._collect_entity_id_drift(
                job, canonical, must_keep_ids=must_keep_ids
            )
            if not has_regex_hits and not entity_drift_ids:
                break
            if force_gate_bypass and has_regex_hits and not entity_drift_ids:
                is_absolute = False
                logger.warning(
                    "[史官] 任务 %s force=true，跳过绝对化正则闸门并强制入库: hits=%s preview=%s",
                    job_id,
                    hit_detail,
                    _preview_text(canonical),
                )
                break
            if attempt < config.rewrite_max_retry:
                gate_feedback = self._build_gate_feedback(
                    hit_detail,
                    entity_drift_ids,
                    force_enabled=force_gate_bypass,
                )
                logger.warning(
                    "[史官] 任务 %s 绝对化闸门命中 (%s/%s): pronoun=%s rel_time=%s rel_place=%s id_drift=%s preview=%s",
                    job_id,
                    attempt + 1,
                    config.rewrite_max_retry + 1,
                    hit_detail["pronoun"],
                    hit_detail["relative_time"],
                    hit_detail["relative_place"],
                    entity_drift_ids,
                    _preview_text(canonical),
                )
                canonical = await self._rewrite(
                    job,
                    job_id=job_id,
                    attempt=attempt + 2,
                    must_keep_entity_ids=entity_drift_ids,
                    gate_feedback=gate_feedback,
                    previous_rewrite=canonical,
                )
            else:
                is_absolute = False
                if entity_drift_ids:
                    logger.warning(
                        "[史官] 任务 %s 实体ID漂移未修复，保留最后一次AI改写结果: ids=%s preview=%s",
                        job_id,
                        entity_drift_ids,
                        _preview_text(canonical),
                    )
                logger.warning(
                    "[史官] 任务 %s 绝对化失败，降级写入: final_hits=%s id_drift=%s preview=%s",
                    job_id,
                    hit_detail,
                    entity_drift_ids,
                    _preview_text(canonical),
                )
        return canonical, is_absolute

    async def _process_job(self, job_id: str, job: dict[str, Any]) -> None:
        logger.info(
            "[史官] 开始处理任务 %s: user=%s group=%s sender=%s perspective=%s has_observations=%s profile_targets=%s",
            job_id,
            job.get("user_id", ""),
            job.get("group_id", ""),
            job.get("sender_id", ""),
            job.get("perspective", ""),
            job.get("has_observations", job.get("has_new_info", False)),
            len(job.get("profile_targets", []) or []),
        )

        # 兼容旧版：优先 observations，fallback new_info
        raw_observations = (
            job.get("observations")
            if "observations" in job
            else job.get("new_info", [])
        )
        if isinstance(raw_observations, str):
            observation_items = (
                [raw_observations.strip()] if raw_observations.strip() else []
            )
        elif isinstance(raw_observations, list):
            observation_items = [
                str(s).strip() for s in raw_observations if str(s).strip()
            ]
        else:
            observation_items = []

        base_metadata: dict[str, Any] = {
            "request_id": job.get("request_id", ""),
            "end_seq": job.get("end_seq", 0),
            "user_id": job.get("user_id", ""),
            "group_id": job.get("group_id", ""),
            "sender_id": job.get("sender_id", ""),
            "request_type": job.get("request_type", ""),
            "timestamp_utc": job.get("timestamp_utc", ""),
            "timestamp_local": job.get("timestamp_local", ""),
            "timestamp_epoch": _resolve_timestamp_epoch(job),
            "timezone": job.get("timezone", ""),
            "location_abs": job.get("location_abs", ""),
            "message_ids": job.get("message_ids", []),
            "perspective": str(job.get("perspective", "")).strip(),
            "schema_version": job.get("schema_version", "final_v1"),
        }

        canonicals: list[str] = []

        if observation_items:
            # 每条 observation 独立改写+入库
            for idx, info_item in enumerate(observation_items):
                sub_job = {**job, "observations": info_item}
                event_id = f"{job_id}_{idx}" if len(observation_items) > 1 else job_id
                canonical, is_absolute = await self._rewrite_and_validate(
                    sub_job, event_id
                )
                meta = {
                    **base_metadata,
                    "has_observations": True,
                    "is_absolute": is_absolute,
                }
                await self._vector_store.upsert_event(event_id, canonical, meta)
                canonicals.append(canonical)
                logger.info(
                    "[史官] 任务 %s 事件入库完成(%s/%s): is_absolute=%s len=%s",
                    event_id,
                    idx + 1,
                    len(observation_items),
                    is_absolute,
                    len(canonical),
                )

        # 侧写合并：传入所有 canonical 文本
        has_obs = (
            job.get("has_observations")
            if "has_observations" in job
            else job.get("has_new_info", False)
        )
        if has_obs and canonicals:
            merged_canonical = "\n".join(canonicals)
            await self._merge_profiles(job, merged_canonical, job_id)

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

    def _build_gate_feedback(
        self,
        hit_detail: dict[str, list[str]],
        entity_drift_ids: list[str],
        *,
        force_enabled: bool,
    ) -> str:
        lines: list[str] = []
        pronouns = [
            str(v).strip() for v in hit_detail.get("pronoun", []) if str(v).strip()
        ]
        rel_times = [
            str(v).strip()
            for v in hit_detail.get("relative_time", [])
            if str(v).strip()
        ]
        rel_places = [
            str(v).strip()
            for v in hit_detail.get("relative_place", [])
            if str(v).strip()
        ]
        if pronouns:
            lines.append(f"- 命中代词: {', '.join(pronouns)}")
        if rel_times:
            lines.append(f"- 命中相对时间: {', '.join(rel_times)}")
        if rel_places:
            lines.append(f"- 命中相对地点: {', '.join(rel_places)}")
        if entity_drift_ids:
            lines.append(f"- 命中实体ID漂移: {', '.join(entity_drift_ids)}")
        lines.append(f"- 当前 force: {'true' if force_enabled else 'false'}")
        if force_enabled:
            lines.append(
                "- force=true 仅可放宽专有名词中的相对词；实体ID漂移仍然不允许。"
            )
        else:
            lines.append("- force=false 时必须彻底消除相对表达并修复ID漂移。")
        return "\n".join(lines)

    def _collect_source_entity_ids(self, job: dict[str, Any]) -> list[str]:
        # 向后兼容：优先 memo/observations，fallback action_summary/new_info
        memo_text = str(
            job.get("memo") if "memo" in job else job.get("action_summary", "")
        )
        observations_text = str(
            job.get("observations")
            if "observations" in job
            else job.get("new_info", "")
        )
        source_parts = [
            memo_text,
            observations_text,
        ]
        source_ids = _collect_unique_id_hits(" ".join(source_parts), limit=50)
        if not source_ids:
            return []

        context_ids: set[str] = set()
        for key in ("sender_id", "user_id", "group_id"):
            value = str(job.get(key, "")).strip()
            if value:
                context_ids.update(_collect_unique_id_hits(value, limit=50))
        message_ids = job.get("message_ids", [])
        if isinstance(message_ids, list):
            for value in message_ids:
                text = str(value).strip()
                if text:
                    context_ids.update(_collect_unique_id_hits(text, limit=50))

        return [sid for sid in source_ids if sid not in context_ids]

    def _collect_entity_id_drift(
        self,
        job: dict[str, Any],
        canonical: str,
        *,
        must_keep_ids: list[str] | None = None,
    ) -> list[str]:
        required_ids = (
            must_keep_ids
            if must_keep_ids is not None
            else self._collect_source_entity_ids(job)
        )
        if not required_ids:
            return []
        canonical_ids = set(_collect_unique_id_hits(canonical, limit=50))
        return [eid for eid in required_ids if eid not in canonical_ids]

    def _extract_required_tool_args(
        self,
        response: dict[str, Any],
        *,
        expected_tool_name: str,
        stage: str,
        job_id: str,
        attempt: int | None = None,
        target: str | None = None,
    ) -> dict[str, Any]:
        suffix = f" stage={stage} expected_tool={expected_tool_name}"
        if attempt is not None:
            suffix += f" attempt={attempt}"
        if target:
            suffix += f" target={target}"

        choices = response.get("choices")
        if not isinstance(choices, list) or not choices:
            logger.error("[史官] 任务 %s 响应缺少 choices:%s", job_id, suffix)
            raise ValueError(f"{stage} 响应缺少 choices")

        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        if not isinstance(message, dict):
            logger.error("[史官] 任务 %s 响应缺少 message:%s", job_id, suffix)
            raise ValueError(f"{stage} 响应缺少 message")

        tool_calls = message.get("tool_calls")
        if not isinstance(tool_calls, list) or not tool_calls:
            logger.error(
                "[史官] 任务 %s 响应缺少 tool_calls:%s content_preview=%s",
                job_id,
                suffix,
                _preview_text(str(message.get("content", ""))),
            )
            raise ValueError(f"{stage} 响应缺少 tool_calls")

        tool_call = tool_calls[0]
        function = tool_call.get("function", {}) if isinstance(tool_call, dict) else {}
        tool_name = str(function.get("name", "")).strip()
        if tool_name != expected_tool_name:
            logger.error(
                "[史官] 任务 %s 工具名不匹配:%s actual_tool=%s",
                job_id,
                suffix,
                tool_name,
            )
            raise ValueError(f"{stage} 工具名不匹配: {tool_name}")

        raw_args = str(function.get("arguments", "{}"))
        try:
            args = json.loads(raw_args)
        except json.JSONDecodeError as exc:
            logger.error(
                "[史官] 任务 %s 工具参数 JSON 解析失败:%s err=%s raw_preview=%s",
                job_id,
                suffix,
                exc,
                _preview_text(raw_args),
            )
            raise
        if not isinstance(args, dict):
            logger.error(
                "[史官] 任务 %s 工具参数类型非法:%s type=%s",
                job_id,
                suffix,
                type(args).__name__,
            )
            raise ValueError(f"{stage} 工具参数类型非法")
        return args

    async def _rewrite(
        self,
        job: dict[str, Any],
        *,
        job_id: str = "",
        attempt: int = 1,
        must_keep_entity_ids: list[str] | None = None,
        gate_feedback: str | None = None,
        previous_rewrite: str | None = None,
    ) -> str:
        from Undefined.utils.resources import read_text_resource

        # 向后兼容：优先 memo，fallback action_summary
        memo = str(job.get("memo") if "memo" in job else job.get("action_summary", ""))
        # 向后兼容：优先 observations，fallback new_info
        observations = str(
            job.get("observations")
            if "observations" in job
            else job.get("new_info", "")
        )
        message_ids_raw = job.get("message_ids", [])
        if isinstance(message_ids_raw, list):
            message_ids = [
                str(item).strip() for item in message_ids_raw if str(item).strip()
            ]
        else:
            message_ids = []
        profile_targets_raw = job.get("profile_targets", [])
        profile_targets_text = "[]"
        if isinstance(profile_targets_raw, list) and profile_targets_raw:
            compact_targets: list[str] = []
            for target in profile_targets_raw:
                if not isinstance(target, dict):
                    continue
                entity_type = str(target.get("entity_type", "")).strip()
                entity_id = str(target.get("entity_id", "")).strip()
                perspective = str(target.get("perspective", "")).strip()
                if not entity_type or not entity_id:
                    continue
                if perspective:
                    compact_targets.append(f"{entity_type}:{entity_id}({perspective})")
                else:
                    compact_targets.append(f"{entity_type}:{entity_id}")
            if compact_targets:
                profile_targets_text = ", ".join(compact_targets)
        logger.debug(
            "[史官] 任务 %s 发起绝对化改写: attempt=%s memo_len=%s observations_len=%s",
            job_id or "unknown",
            attempt,
            len(memo),
            len(observations),
        )

        template = read_text_resource("res/prompts/historian_rewrite.md")
        source_message = str(job.get("source_message", "")).strip()
        recent_messages_raw = job.get("recent_messages", [])
        recent_messages: list[str] = []
        if isinstance(recent_messages_raw, list):
            recent_messages = [
                str(item).strip() for item in recent_messages_raw if str(item).strip()
            ]
        recent_messages_text = "\n".join(f"- {line}" for line in recent_messages)
        prompt = template.format(
            request_id=job.get("request_id", ""),
            end_seq=job.get("end_seq", 0),
            timestamp_local=job.get("timestamp_local", ""),
            timezone=job.get("timezone", "Asia/Shanghai"),
            bot_name=job.get("bot_name", "Undefined"),
            user_id=job.get("user_id", ""),
            group_id=job.get("group_id", ""),
            sender_id=job.get("sender_id", ""),
            sender_name=job.get("sender_name", ""),
            group_name=job.get("group_name", ""),
            message_ids=", ".join(message_ids) if message_ids else "[]",
            perspective=job.get("perspective", ""),
            profile_targets=profile_targets_text,
            force="true" if _coerce_bool(job.get("force", False)) else "false",
            action_summary=memo,
            new_info=observations,
            memo=memo,
            observations=observations,
            source_message=source_message or "（无）",
            recent_messages=recent_messages_text or "（无）",
        )
        if must_keep_entity_ids:
            unique_ids = [sid for sid in must_keep_entity_ids if str(sid).strip()]
            if unique_ids:
                prompt += (
                    "\n\n额外硬约束（本轮必须满足）：\n"
                    "- 以下实体ID在原始摘要中已显式出现，改写结果必须原样保留，不得改写为 sender_id 或其他ID：\n"
                    f"- must_keep_entity_ids: {', '.join(unique_ids)}\n"
                    "- 若无法判断昵称，请至少保留对应的数字ID。"
                )
        if gate_feedback and str(gate_feedback).strip():
            gate_parts: list[str] = [
                "",
                "",
                "上次提交被“绝对化闸门”拦截，"
                "原因如下（请在上次改写结果基础上逐项修正后再提交）：",
                gate_feedback.strip(),
                "- 返回前请自检：不得包含代词/相对时间/相对地点；"
                "且不得丢失必须保留的实体ID。",
                "- 若闸门属于误判（如命中词属于专有名词、用户昵称、作品名等），"
                "AI 调用 end 工具时可使用 force=true 跳过正则闸门。",
            ]
            prompt += "\n".join(gate_parts)
            if previous_rewrite and str(previous_rewrite).strip():
                prompt += (
                    "\n\n你上次的改写结果"
                    "（请在此基础上修正，而非从头改写）：\n" + previous_rewrite.strip()
                )
        response = await self._ai_client.submit_background_llm_call(
            model_config=self._model_config or self._ai_client.agent_config,
            messages=[{"role": "user", "content": prompt}],
            tools=[_REWRITE_TOOL],
            tool_choice={"type": "function", "function": {"name": "submit_rewrite"}},
            call_type="historian_rewrite",
        )
        args = self._extract_required_tool_args(
            response=response,
            expected_tool_name="submit_rewrite",
            stage="historian_rewrite",
            job_id=job_id or "unknown",
            attempt=attempt,
        )

        text = str(args.get("text", "")).strip()
        logger.debug(
            "[史官] 任务 %s 收到改写候选: attempt=%s len=%s preview=%s",
            job_id or "unknown",
            attempt,
            len(text),
            _preview_text(text),
        )
        return text

    def _resolve_profile_targets(self, job: dict[str, Any]) -> list[dict[str, str]]:
        targets: list[dict[str, str]] = []
        seen: set[tuple[str, str]] = set()
        raw_targets = job.get("profile_targets")
        if isinstance(raw_targets, list):
            for item in raw_targets:
                if not isinstance(item, dict):
                    continue
                entity_type = str(item.get("entity_type", "")).strip()
                raw_entity_id = item.get("entity_id")
                entity_id = (
                    str(raw_entity_id).strip() if raw_entity_id is not None else ""
                )
                if entity_type not in {"user", "group"} or not entity_id:
                    continue
                key = (entity_type, entity_id)
                if key in seen:
                    continue
                seen.add(key)
                targets.append(
                    {
                        "entity_type": entity_type,
                        "entity_id": entity_id,
                        "perspective": str(item.get("perspective", "")).strip(),
                        "preferred_name": str(item.get("preferred_name", "")).strip(),
                    }
                )
        if targets:
            return targets

        # 向后兼容旧任务：沿用单目标策略。
        entity_type = "group" if str(job.get("group_id", "")).strip() else "user"
        entity_id = str(
            job.get("group_id") or job.get("user_id") or job.get("sender_id", "")
        ).strip()
        if entity_id:
            targets.append(
                {
                    "entity_type": entity_type,
                    "entity_id": entity_id,
                    "perspective": "legacy",
                    "preferred_name": "",
                }
            )
        return targets

    def _resolve_profile_name(
        self, target: dict[str, str], current_profile: str
    ) -> str:
        preferred_name = str(target.get("preferred_name", "")).strip()
        if preferred_name:
            return preferred_name
        current_name = _extract_frontmatter_name(current_profile)
        if current_name:
            return current_name
        entity_id = str(target.get("entity_id", "")).strip()
        if str(target.get("entity_type", "")).strip() == "group":
            return f"GID:{entity_id}"
        return f"UID:{entity_id}"

    async def _merge_profiles(
        self, job: dict[str, Any], canonical: str, event_id: str
    ) -> None:
        targets = self._resolve_profile_targets(job)
        if not targets:
            logger.warning("[史官] 任务 %s 侧写合并跳过：缺少目标实体", event_id)
            return
        logger.info(
            "[史官] 任务 %s 开始合并侧写: target_count=%s targets=%s",
            event_id,
            len(targets),
            [
                (t["entity_type"], t["entity_id"], t.get("perspective", ""))
                for t in targets
            ],
        )
        success_count = 0
        for index, target in enumerate(targets, start=1):
            try:
                merged = await self._merge_profile_target(
                    job=job,
                    canonical=canonical,
                    event_id=event_id,
                    target=target,
                    target_index=index,
                    target_count=len(targets),
                )
                if merged:
                    success_count += 1
            except Exception as exc:
                logger.exception(
                    "[史官] 任务 %s 侧写目标合并失败: target=%s:%s perspective=%s err=%s",
                    event_id,
                    target.get("entity_type", ""),
                    target.get("entity_id", ""),
                    target.get("perspective", ""),
                    exc,
                )
        logger.info(
            "[史官] 任务 %s 侧写合并结束: success=%s total=%s",
            event_id,
            success_count,
            len(targets),
        )

    async def _merge_profile_target(
        self,
        *,
        job: dict[str, Any],
        canonical: str,
        event_id: str,
        target: dict[str, str],
        target_index: int,
        target_count: int,
    ) -> bool:
        import yaml

        entity_type = str(target.get("entity_type", "")).strip()
        entity_id = str(target.get("entity_id", "")).strip()
        perspective = str(target.get("perspective", "")).strip()
        if entity_type not in {"user", "group"} or not entity_id:
            logger.warning(
                "[史官] 任务 %s 侧写目标非法，跳过: target=%s",
                event_id,
                target,
            )
            return False
        logger.info(
            "[史官] 任务 %s 合并侧写目标(%s/%s): entity_type=%s entity_id=%s perspective=%s",
            event_id,
            target_index,
            target_count,
            entity_type,
            entity_id,
            perspective,
        )

        current = (
            await self._profile_storage.read_profile(entity_type, entity_id)
            or "（暂无侧写）"
        )
        effective_name = self._resolve_profile_name(target, current)

        from Undefined.utils.resources import read_text_resource

        template = read_text_resource("res/prompts/historian_profile_merge.md")
        message_ids_raw = job.get("message_ids", [])
        if isinstance(message_ids_raw, list):
            message_ids = [
                str(item).strip() for item in message_ids_raw if str(item).strip()
            ]
        else:
            message_ids = []
        prompt = template.format(
            current_profile=_escape_braces(current),
            canonical_text=_escape_braces(canonical),
            new_info=_escape_braces(
                "\n".join(job.get("observations", job.get("new_info", [])))
                if isinstance(job.get("observations", job.get("new_info")), list)
                else str(job.get("observations", job.get("new_info", "")))
            ),
            observations=_escape_braces(
                "\n".join(job.get("observations", job.get("new_info", [])))
                if isinstance(job.get("observations", job.get("new_info")), list)
                else str(job.get("observations", job.get("new_info", "")))
            ),
            target_entity_type=entity_type,
            target_entity_id=entity_id,
            target_perspective=perspective,
            target_display_name=_escape_braces(effective_name),
            request_type=_escape_braces(str(job.get("request_type", ""))),
            user_id=_escape_braces(str(job.get("user_id", ""))),
            group_id=_escape_braces(str(job.get("group_id", ""))),
            sender_id=_escape_braces(str(job.get("sender_id", ""))),
            sender_name=_escape_braces(str(job.get("sender_name", ""))),
            group_name=_escape_braces(str(job.get("group_name", ""))),
            timestamp_local=_escape_braces(str(job.get("timestamp_local", ""))),
            timezone=_escape_braces(str(job.get("timezone", ""))),
            event_id=_escape_braces(event_id),
            request_id=_escape_braces(str(job.get("request_id", ""))),
            end_seq=_escape_braces(str(job.get("end_seq", 0))),
            message_ids=_escape_braces(", ".join(message_ids) if message_ids else "[]"),
            action_summary=_escape_braces(
                str(job.get("memo", job.get("action_summary", "")))
            ),
            memo=_escape_braces(str(job.get("memo", job.get("action_summary", "")))),
            source_message=_escape_braces(str(job.get("source_message", ""))),
            recent_messages=_escape_braces(
                "\n".join(
                    f"- {str(item).strip()}"
                    for item in (job.get("recent_messages", []) or [])
                    if str(item).strip()
                )
                or "（无）"
            ),
        )

        response = await self._ai_client.submit_background_llm_call(
            model_config=self._model_config or self._ai_client.agent_config,
            messages=[{"role": "user", "content": prompt}],
            tools=[_PROFILE_TOOL],
            tool_choice={"type": "function", "function": {"name": "update_profile"}},
            call_type="historian_profile_merge",
        )
        args = self._extract_required_tool_args(
            response=response,
            expected_tool_name="update_profile",
            stage="historian_profile_merge",
            job_id=event_id,
            target=f"{entity_type}:{entity_id}",
        )

        skip = bool(args.get("skip", False))
        skip_reason = str(args.get("skip_reason", "")).strip()
        if skip:
            logger.info(
                "[史官] 任务 %s 侧写更新跳过: target=%s:%s perspective=%s reason=%s",
                event_id,
                entity_type,
                entity_id,
                perspective,
                skip_reason or "unspecified",
            )
            return False

        summary = str(args.get("summary", "")).strip()
        if not summary:
            logger.info(
                "[史官] 任务 %s 侧写更新跳过: target=%s:%s perspective=%s reason=empty_summary",
                event_id,
                entity_type,
                entity_id,
                perspective,
            )
            return False

        raw_tags = args.get("tags", [])
        tags: list[str] = []
        if isinstance(raw_tags, list):
            tags = [str(item).strip() for item in raw_tags if str(item).strip()]
            tags = tags[:10]

        llm_name = str(args.get("name", "")).strip()
        if llm_name and llm_name != effective_name:
            logger.info(
                "[史官] 任务 %s 侧写名称已锁定: target=%s:%s llm_name=%s effective_name=%s",
                event_id,
                entity_type,
                entity_id,
                llm_name,
                effective_name,
            )

        frontmatter = {
            "entity_type": entity_type,
            "entity_id": entity_id,
            "name": effective_name,
            "tags": tags,
            "updated_at": datetime.now().isoformat(),
            "source_event_id": event_id,
        }
        content = f"---\n{yaml.dump(frontmatter, allow_unicode=True)}---\n{summary}"

        await self._profile_storage.write_profile(entity_type, entity_id, content)
        logger.info(
            "[史官] 任务 %s 侧写文件写入完成: entity_type=%s entity_id=%s tags=%s perspective=%s",
            event_id,
            entity_type,
            entity_id,
            tags,
            perspective,
        )
        await self._vector_store.upsert_profile(
            f"{entity_type}:{entity_id}",
            f"标签: {', '.join(tags)}\n{summary}" if tags else summary,
            {
                "entity_type": entity_type,
                "entity_id": entity_id,
                "name": effective_name,
            },
        )
        logger.info(
            "[史官] 任务 %s 侧写向量入库完成: profile_id=%s perspective=%s",
            event_id,
            f"{entity_type}:{entity_id}",
            perspective,
        )
        return True
