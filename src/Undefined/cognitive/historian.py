"""后台史官 Worker，轮询队列处理任务。"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Callable

logger = logging.getLogger(__name__)

_MAX_LOG_PREVIEW_LEN = 200

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

_READ_PROFILE_TOOL = {
    "type": "function",
    "function": {
        "name": "read_profile",
        "description": "读取指定实体的当前侧写内容",
        "parameters": {
            "type": "object",
            "properties": {
                "entity_type": {
                    "type": "string",
                    "enum": ["user", "group"],
                    "description": "实体类型：user 或 group",
                },
                "entity_id": {
                    "type": "string",
                    "description": "实体 ID（用户 QQ 号或群号）",
                },
            },
            "required": ["entity_type", "entity_id"],
        },
    },
}

_PROFILE_TOOL = {
    "type": "function",
    "function": {
        "name": "update_profile",
        "description": "更新用户/群侧写。调用前必须先用 read_profile 查看当前内容",
        "parameters": {
            "type": "object",
            "properties": {
                "entity_type": {
                    "type": "string",
                    "enum": ["user", "group"],
                    "description": "实体类型：user 或 group",
                },
                "entity_id": {
                    "type": "string",
                    "description": "实体 ID（用户 QQ 号或群号）",
                },
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
            "required": ["entity_type", "entity_id", "skip", "name", "tags", "summary"],
        },
    },
}


def _preview_text(text: str, max_len: int = _MAX_LOG_PREVIEW_LEN) -> str:
    compact = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(compact) <= max_len:
        return compact
    return f"{compact[:max_len]}..."


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
        self._inflight_tasks: set[asyncio.Task[None]] = set()

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
        dispatch_count = 0
        logger.info("[史官] 轮询循环已开始")
        while not self._stop_event.is_set():
            result = await self._job_queue.dequeue()
            if result:
                job_id, job = result
                task = asyncio.create_task(self._process_job_with_retry(job_id, job))
                self._inflight_tasks.add(task)
                task.add_done_callback(self._inflight_tasks.discard)
                dispatch_count += 1
                logger.info(
                    "[史官] 任务已发车: job_id=%s inflight=%s",
                    job_id,
                    len(self._inflight_tasks),
                )

            config = self._config_getter()
            if (
                config.failed_cleanup_interval > 0
                and dispatch_count > 0
                and dispatch_count % config.failed_cleanup_interval == 0
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

        if self._inflight_tasks:
            logger.info(
                "[史官] 等待在途任务收敛: inflight=%s", len(self._inflight_tasks)
            )
            await asyncio.gather(*list(self._inflight_tasks), return_exceptions=True)
        logger.info("[史官] 轮询循环已结束")

    async def _process_job_with_retry(self, job_id: str, job: dict[str, Any]) -> None:
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

    async def _rewrite_and_validate(self, job: dict[str, Any], job_id: str) -> str:
        """改写为绝对化事件文本。"""
        canonical = await self._rewrite(job, job_id=job_id)
        return canonical

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
                canonical = await self._rewrite_and_validate(sub_job, event_id)
                meta = {
                    **base_metadata,
                    "has_observations": True,
                }
                await self._vector_store.upsert_event(event_id, canonical, meta)
                canonicals.append(canonical)
                logger.info(
                    "[史官] 任务 %s 事件入库完成(%s/%s): len=%s",
                    event_id,
                    idx + 1,
                    len(observation_items),
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
            "[史官] 任务 %s 发起绝对化改写: memo_len=%s observations_len=%s",
            job_id or "unknown",
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
        )

        text = str(args.get("text", "")).strip()
        logger.debug(
            "[史官] 任务 %s 收到改写结果: len=%s preview=%s",
            job_id or "unknown",
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

    async def _write_profile(
        self,
        *,
        entity_type: str,
        entity_id: str,
        effective_name: str,
        tags: list[str],
        summary: str,
        event_id: str,
        perspective: str,
    ) -> None:
        import yaml

        frontmatter: dict[str, Any] = {
            "entity_type": entity_type,
            "entity_id": entity_id,
            "name": effective_name,
            "tags": tags,
            "updated_at": datetime.now().isoformat(),
            "source_event_id": event_id,
        }
        if entity_type == "user":
            frontmatter["nickname"] = effective_name
            frontmatter["qq"] = entity_id
        else:
            frontmatter["group_name"] = effective_name
            frontmatter["group_id"] = entity_id
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

        profile_doc_lines: list[str] = []
        if entity_type == "user":
            profile_doc_lines.append(f"昵称: {effective_name}")
            profile_doc_lines.append(f"QQ号: {entity_id}")
        else:
            profile_doc_lines.append(f"群名: {effective_name}")
            profile_doc_lines.append(f"群号: {entity_id}")
        if tags:
            profile_doc_lines.append(f"标签: {', '.join(tags)}")
        profile_doc_lines.append(summary)
        profile_doc = "\n".join(line for line in profile_doc_lines if line.strip())

        profile_metadata: dict[str, Any] = {
            "entity_type": entity_type,
            "entity_id": entity_id,
            "name": effective_name,
        }
        if entity_type == "user":
            profile_metadata["nickname"] = effective_name
            profile_metadata["qq"] = entity_id
        else:
            profile_metadata["group_name"] = effective_name
            profile_metadata["group_id"] = entity_id

        await self._vector_store.upsert_profile(
            f"{entity_type}:{entity_id}",
            profile_doc,
            profile_metadata,
        )
        logger.info(
            "[史官] 任务 %s 侧写向量入库完成: profile_id=%s perspective=%s",
            event_id,
            f"{entity_type}:{entity_id}",
            perspective,
        )

    @staticmethod
    def _historical_event_dedupe_key(
        event: dict[str, Any],
    ) -> tuple[str, str, str, str, str]:
        metadata = event.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}
        return (
            str(event.get("document", "")).strip(),
            str(metadata.get("timestamp_local", "")).strip(),
            str(metadata.get("sender_id", "")).strip(),
            str(metadata.get("user_id", "")).strip(),
            str(metadata.get("group_id", "")).strip(),
        )

    async def _query_user_history_events_for_profile_merge(
        self,
        *,
        query_text: str,
        entity_id: str,
        top_k: int,
    ) -> list[dict[str, Any]]:
        """用户历史检索兼容路径：分别按 sender_id/user_id 查询并合并去重。

        Compatibility path for user history retrieval:
        query sender_id/user_id separately, then merge and dedupe.
        """
        safe_top_k = max(1, int(top_k))
        sender_query = self._vector_store.query_events(
            query_text,
            top_k=safe_top_k,
            where={"sender_id": entity_id},
            apply_mmr=True,
        )
        user_query = self._vector_store.query_events(
            query_text,
            top_k=safe_top_k,
            where={"user_id": entity_id},
            apply_mmr=True,
        )
        sender_events_raw, user_events_raw = await asyncio.gather(
            sender_query, user_query
        )
        merged_events = list(sender_events_raw) + list(user_events_raw)

        deduped: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str, str, str]] = set()
        for event in merged_events:
            key = self._historical_event_dedupe_key(event)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(event)
            if len(deduped) >= safe_top_k:
                break
        return deduped

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

        preferred_name = str(target.get("preferred_name", "")).strip()

        # 检索该实体的历史事件作为 merge 参考
        observations_raw = job.get("observations", job.get("new_info", []))
        observations_text = (
            "\n".join(observations_raw)
            if isinstance(observations_raw, list)
            else str(observations_raw)
        )
        if entity_type == "group":
            historical_events = await self._vector_store.query_events(
                observations_text,
                top_k=8,
                where={"group_id": entity_id},
                apply_mmr=True,
            )
        else:
            historical_events = await self._query_user_history_events_for_profile_merge(
                query_text=observations_text,
                entity_id=entity_id,
                top_k=8,
            )
        historical_lines = (
            "\n".join(
                f"- [{e['metadata'].get('timestamp_local', '')}] {e['document']}"
                for e in historical_events
            )
            or "（暂无历史事件）"
        )

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
            historical_events=_escape_braces(historical_lines),
            canonical_text=_escape_braces(canonical),
            observations=_escape_braces(observations_text),
            new_info=_escape_braces(observations_text),
            target_entity_type=entity_type,
            target_entity_id=entity_id,
            target_perspective=perspective,
            target_display_name=_escape_braces(preferred_name or entity_id),
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
            memo=_escape_braces(str(job.get("memo", job.get("action_summary", "")))),
            action_summary=_escape_braces(
                str(job.get("memo", job.get("action_summary", "")))
            ),
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

        messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]
        tools = [_READ_PROFILE_TOOL, _PROFILE_TOOL]
        result = False
        max_turns = 100

        for turn in range(max_turns):
            response = await self._ai_client.submit_background_llm_call(
                model_config=self._model_config or self._ai_client.agent_config,
                messages=messages,
                tools=tools,
                tool_choice="auto",
                call_type="historian_profile_merge",
            )

            choices = response.get("choices") or []
            if not choices:
                logger.warning("[史官] 任务 %s turn=%s 响应无 choices", event_id, turn)
                break
            message = choices[0].get("message") if isinstance(choices[0], dict) else {}
            if not isinstance(message, dict):
                break

            tool_calls = message.get("tool_calls") or []
            if not tool_calls:
                logger.info(
                    "[史官] 任务 %s turn=%s 无 tool_calls，结束", event_id, turn
                )
                break

            # 追加 assistant 轮次
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "tool_calls": tool_calls,
            }
            if message.get("content"):
                assistant_msg["content"] = message["content"]
            messages.append(assistant_msg)

            tool_results: list[dict[str, Any]] = []
            done = False

            for tc in tool_calls:
                if not isinstance(tc, dict):
                    continue
                func = tc.get("function") or {}
                tc_name = str(func.get("name", "")).strip()
                tc_id = str(tc.get("id", "")).strip()
                try:
                    tc_args: dict[str, Any] = json.loads(
                        str(func.get("arguments", "{}"))
                    )
                except json.JSONDecodeError:
                    tc_args = {}

                if tc_name == "read_profile":
                    rp_et = str(tc_args.get("entity_type", "")).strip()
                    rp_eid = str(tc_args.get("entity_id", "")).strip()
                    if (
                        rp_et not in {"user", "group"}
                        or not rp_eid
                        or not rp_eid.isalnum()
                    ):
                        tc_content = "错误：entity_type 或 entity_id 无效"
                    else:
                        profile_text = await self._profile_storage.read_profile(
                            rp_et, rp_eid
                        )
                        tc_content = profile_text or "（暂无侧写）"
                    logger.info(
                        "[史官] 任务 %s read_profile: %s:%s len=%s",
                        event_id,
                        rp_et,
                        rp_eid,
                        len(tc_content),
                    )
                    tool_results.append(
                        {"role": "tool", "tool_call_id": tc_id, "content": tc_content}
                    )

                elif tc_name == "update_profile":
                    up_et = str(tc_args.get("entity_type", entity_type)).strip()
                    up_eid = str(tc_args.get("entity_id", entity_id)).strip()
                    if (
                        up_et not in {"user", "group"}
                        or not up_eid
                        or not up_eid.isalnum()
                    ):
                        tool_results.append(
                            {
                                "role": "tool",
                                "tool_call_id": tc_id,
                                "content": "错误：entity_type 或 entity_id 无效",
                            }
                        )
                        continue
                    raw_skip = tc_args.get("skip", False)
                    skip = (
                        raw_skip.lower() not in ("false", "0", "no", "")
                        if isinstance(raw_skip, str)
                        else bool(raw_skip)
                    )
                    if skip:
                        skip_reason = str(tc_args.get("skip_reason", "")).strip()
                        logger.info(
                            "[史官] 任务 %s 侧写更新跳过: target=%s:%s perspective=%s reason=%s",
                            event_id,
                            up_et,
                            up_eid,
                            perspective,
                            skip_reason or "unspecified",
                        )
                        tool_results.append(
                            {
                                "role": "tool",
                                "tool_call_id": tc_id,
                                "content": f"已跳过: {skip_reason}",
                            }
                        )
                        done = True
                        continue

                    summary = str(tc_args.get("summary", "")).strip()
                    if not summary:
                        logger.info(
                            "[史官] 任务 %s 侧写更新跳过: target=%s:%s reason=empty_summary",
                            event_id,
                            up_et,
                            up_eid,
                        )
                        tool_results.append(
                            {
                                "role": "tool",
                                "tool_call_id": tc_id,
                                "content": "错误：summary 为空",
                            }
                        )
                        continue
                    raw_tags = tc_args.get("tags", [])
                    up_tags: list[str] = []
                    if isinstance(raw_tags, list):
                        up_tags = [str(t).strip() for t in raw_tags if str(t).strip()][
                            :10
                        ]

                    llm_name = str(tc_args.get("name", "")).strip()
                    is_target = up_et == entity_type and up_eid == entity_id
                    name_hint = preferred_name if is_target else ""
                    if not llm_name and not name_hint:
                        existing = await self._profile_storage.read_profile(
                            up_et, up_eid
                        )
                        fallback_name = _extract_frontmatter_name(existing or "")
                    else:
                        fallback_name = ""
                    effective_name = (
                        name_hint
                        or llm_name
                        or fallback_name
                        or (f"GID:{up_eid}" if up_et == "group" else f"UID:{up_eid}")
                    )

                    await self._write_profile(
                        entity_type=up_et,
                        entity_id=up_eid,
                        effective_name=effective_name,
                        tags=up_tags,
                        summary=summary,
                        event_id=event_id,
                        perspective=perspective,
                    )
                    tool_results.append(
                        {"role": "tool", "tool_call_id": tc_id, "content": "侧写已更新"}
                    )
                    result = True
                    done = True

                else:
                    tool_results.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc_id,
                            "content": f"未知工具: {tc_name}",
                        }
                    )

            messages.extend(tool_results)
            if done:
                break

        return result
