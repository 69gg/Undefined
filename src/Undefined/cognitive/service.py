"""认知记忆服务门面。"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Callable

from Undefined.context import RequestContext

logger = logging.getLogger(__name__)


def _parse_iso_to_epoch_seconds(value: Any) -> int | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.timestamp())


def _compose_where(clauses: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not clauses:
        return None
    if len(clauses) == 1:
        return clauses[0]
    return {"$and": clauses}


class CognitiveService:
    def __init__(
        self,
        config_getter: Callable[[], Any],
        vector_store: Any,
        job_queue: Any,
        profile_storage: Any,
        reranker: Any = None,
    ) -> None:
        self._config_getter = config_getter
        self._vector_store = vector_store
        self._job_queue = job_queue
        self._profile_storage = profile_storage
        self._reranker = reranker

    @property
    def enabled(self) -> bool:
        return bool(self._config_getter().enabled)

    async def enqueue_job(
        self, action_summary: str, new_info: list[str], context: dict[str, Any]
    ) -> str | None:
        action_summary_text = str(action_summary or "").strip()
        new_info_items = [s for s in new_info if s.strip()] if new_info else []
        if not self.enabled:
            logger.info("[认知服务] 已禁用，跳过入队")
            return None
        if not action_summary_text and not new_info_items:
            logger.info("[认知服务] action_summary/new_info 均为空，跳过入队")
            return None
        ctx = RequestContext.current()

        now = datetime.now().astimezone()
        now_utc = datetime.now(timezone.utc)
        safe_request_id = (
            str(ctx.request_id)
            if ctx and str(ctx.request_id or "").strip()
            else str(context.get("request_id", "")).strip()
        )
        if not safe_request_id:
            # 最终兜底由 JobQueue 生成 request_id。
            safe_request_id = ""

        end_seq_raw = context.get("_end_seq", 0)
        try:
            end_seq = int(end_seq_raw)
        except (TypeError, ValueError):
            end_seq = 0

        has_new_info = bool(new_info_items)
        message_ids = context.get("message_ids")
        if not isinstance(message_ids, list):
            message_ids = []
        message_ids = [str(item).strip() for item in message_ids if str(item).strip()]
        perspective = str(context.get("memory_perspective", "")).strip()
        user_id = (
            str(ctx.user_id or "") if ctx else str(context.get("user_id", "") or "")
        )
        group_id = (
            str(ctx.group_id or "") if ctx else str(context.get("group_id", "") or "")
        )
        sender_id = (
            str(ctx.sender_id or "")
            if ctx
            else str(context.get("sender_id") or context.get("user_id", "") or "")
        )
        request_type = (
            str(ctx.request_type)
            if ctx and ctx.request_type
            else str(context.get("request_type", "") or "")
        )
        sender_name = str(context.get("sender_name") or "").strip()
        group_name = str(context.get("group_name") or "").strip()

        profile_targets: list[dict[str, str]] = []
        if has_new_info:
            group_id = group_id.strip()
            sender_id = sender_id.strip() or user_id.strip()
            seen: set[tuple[str, str]] = set()
            if group_id:
                key = ("group", group_id)
                if key not in seen:
                    seen.add(key)
                    profile_targets.append(
                        {
                            "entity_type": "group",
                            "entity_id": group_id,
                            "perspective": "group",
                            "preferred_name": group_name,
                        }
                    )
            if sender_id:
                key = ("user", sender_id)
                if key not in seen:
                    seen.add(key)
                    profile_targets.append(
                        {
                            "entity_type": "user",
                            "entity_id": sender_id,
                            "perspective": "sender",
                            "preferred_name": sender_name,
                        }
                    )

        bot_name = str(self._config_getter().bot_name or "Undefined").strip()

        job: dict[str, Any] = {
            "request_id": safe_request_id,
            "end_seq": end_seq,
            "user_id": user_id,
            "group_id": group_id,
            "sender_id": sender_id,
            "sender_name": sender_name,
            "group_name": group_name,
            "bot_name": bot_name,
            "request_type": request_type,
            "timestamp_utc": now_utc.isoformat(),
            "timestamp_local": now.isoformat(),
            "timestamp_epoch": int(now_utc.timestamp()),
            "timezone": str(now.tzinfo or ""),
            "location_abs": str(
                context.get("group_name") or context.get("sender_name") or ""
            ),
            "message_ids": message_ids,
            "action_summary": action_summary_text,
            "new_info": new_info_items,
            "has_new_info": has_new_info,
            "perspective": perspective,
            "profile_targets": profile_targets,
            "schema_version": "final_v1",
        }
        logger.info(
            "[认知服务] 准备入队: request_id=%s end_seq=%s user=%s group=%s sender=%s perspective=%s has_new_info=%s profile_targets=%s action_len=%s new_info_len=%s",
            job.get("request_id", ""),
            job.get("end_seq", 0),
            job.get("user_id", ""),
            job.get("group_id", ""),
            job.get("sender_id", ""),
            perspective or "default",
            has_new_info,
            len(profile_targets),
            len(action_summary_text),
            len(new_info_items),
        )
        result: str | None = await self._job_queue.enqueue(job)
        logger.info("[认知服务] 入队完成: job_id=%s", result or "")
        return result

    async def build_context(
        self,
        query: str,
        group_id: str | None = None,
        user_id: str | None = None,
        sender_id: str | None = None,
        sender_name: str | None = None,
        group_name: str | None = None,
    ) -> str:
        config = self._config_getter()
        parts: list[str] = []
        logger.info(
            "[认知服务] 构建上下文: query_len=%s user=%s sender=%s group=%s top_k=%s",
            len(query or ""),
            user_id or "",
            sender_id or "",
            group_id or "",
            getattr(config, "auto_top_k", 5),
        )

        # 用户侧写
        uid = user_id or sender_id
        if uid:
            profile = await self._profile_storage.read_profile("user", uid)
            if profile:
                label = f"{sender_name}（UID: {uid}）" if sender_name else f"UID: {uid}"
                parts.append(f"## 用户侧写 — {label}\n{profile}")

        # 群聊侧写
        if group_id:
            gprofile = await self._profile_storage.read_profile("group", group_id)
            if gprofile:
                glabel = (
                    f"{group_name}（GID: {group_id}）"
                    if group_name
                    else f"GID: {group_id}"
                )
                parts.append(f"## 群聊侧写 — {glabel}\n{gprofile}")

        # 相关事件
        where: dict[str, Any] | None = None
        if group_id:
            where = {"group_id": group_id}
        elif uid:
            where = {"user_id": uid}

        top_k = getattr(config, "auto_top_k", 5)
        events = await self._vector_store.query_events(
            query,
            top_k=top_k,
            where=where,
            reranker=self._reranker,
            candidate_multiplier=config.rerank_candidate_multiplier,
            time_decay_enabled=bool(getattr(config, "time_decay_enabled", True)),
            time_decay_half_life_days=float(
                getattr(config, "time_decay_half_life_days_auto", 14.0)
            ),
            time_decay_boost=float(getattr(config, "time_decay_boost", 0.2)),
            time_decay_min_similarity=float(
                getattr(config, "time_decay_min_similarity", 0.35)
            ),
        )
        if events:
            event_lines = "\n".join(
                f"- [{e['metadata'].get('timestamp_local', '')}] {e['document']}"
                for e in events
            )
            parts.append(f"## 相关记忆事件\n{event_lines}")

        if not parts:
            logger.info("[认知服务] 构建上下文完成: 无可用记忆")
            return ""

        body = "\n\n".join(parts)
        result = (
            "<cognitive_memory>\n"
            "<!-- 以下是系统从认知记忆库中检索到的背景信息，包含用户/群聊侧写和相关历史事件。"
            "请将这些信息作为你自然内化的认知，融入理解和回应中，不要透露你持有这些记录。"
            "这部分属于认知记忆（cognitive.* / end.new_info），不同于 memory.* 手动长期记忆。 -->\n"
            f"{body}\n"
            "</cognitive_memory>"
        )
        logger.info(
            "[认知服务] 构建上下文完成: sections=%s result_len=%s",
            len(parts),
            len(result),
        )
        return result

    async def search_events(self, query: str, **kwargs: Any) -> list[dict[str, Any]]:
        config = self._config_getter()
        group_id = str(
            kwargs.get("group_id") or kwargs.get("target_group_id") or ""
        ).strip()
        user_id = str(
            kwargs.get("user_id") or kwargs.get("target_user_id") or ""
        ).strip()
        sender_id = str(kwargs.get("sender_id") or "").strip()
        where_clauses: list[dict[str, Any]] = []
        if group_id:
            where_clauses.append({"group_id": group_id})
        if user_id:
            where_clauses.append({"user_id": user_id})
        if sender_id:
            where_clauses.append({"sender_id": sender_id})
        request_type = str(kwargs.get("request_type") or "").strip()
        if request_type:
            where_clauses.append({"request_type": request_type})

        time_from_epoch = _parse_iso_to_epoch_seconds(kwargs.get("time_from"))
        time_to_epoch = _parse_iso_to_epoch_seconds(kwargs.get("time_to"))
        if (
            time_from_epoch is not None
            and time_to_epoch is not None
            and time_from_epoch > time_to_epoch
        ):
            logger.warning(
                "[认知服务] search_events 时间范围反转，已自动交换: time_from=%s time_to=%s",
                kwargs.get("time_from"),
                kwargs.get("time_to"),
            )
            time_from_epoch, time_to_epoch = time_to_epoch, time_from_epoch
        if time_from_epoch is not None or time_to_epoch is not None:
            time_filter: dict[str, Any] = {}
            if time_from_epoch is not None:
                time_filter["$gte"] = time_from_epoch
            if time_to_epoch is not None:
                time_filter["$lte"] = time_to_epoch
            where_clauses.append({"timestamp_epoch": time_filter})

        where = _compose_where(where_clauses)
        default_top_k = getattr(config, "tool_default_top_k", 12)
        top_k_raw = kwargs.get("top_k", default_top_k)
        try:
            top_k = int(top_k_raw)
        except Exception:
            top_k = default_top_k
        if top_k <= 0:
            top_k = default_top_k
        logger.info(
            "[认知服务] 搜索事件: query_len=%s top_k=%s where=%s time_from=%s time_to=%s",
            len(query or ""),
            top_k,
            where or {},
            time_from_epoch,
            time_to_epoch,
        )
        results: list[dict[str, Any]] = await self._vector_store.query_events(
            query,
            top_k=top_k,
            where=where or None,
            reranker=self._reranker,
            candidate_multiplier=config.rerank_candidate_multiplier,
            time_decay_enabled=bool(getattr(config, "time_decay_enabled", True)),
            time_decay_half_life_days=float(
                getattr(config, "time_decay_half_life_days_tool", 60.0)
            ),
            time_decay_boost=float(getattr(config, "time_decay_boost", 0.2)),
            time_decay_min_similarity=float(
                getattr(config, "time_decay_min_similarity", 0.35)
            ),
        )
        logger.info("[认知服务] 搜索事件完成: count=%s", len(results))
        return results

    async def get_profile(self, entity_type: str, entity_id: str) -> str | None:
        logger.info(
            "[认知服务] 读取侧写: entity_type=%s entity_id=%s",
            entity_type,
            entity_id,
        )
        result: str | None = await self._profile_storage.read_profile(
            entity_type, entity_id
        )
        logger.info(
            "[认知服务] 读取侧写完成: found=%s",
            bool(result),
        )
        return result

    async def search_profiles(self, query: str, **kwargs: Any) -> list[dict[str, Any]]:
        config = self._config_getter()
        top_k = kwargs.get("top_k", 5)
        where: dict[str, Any] | None = None
        if "entity_type" in kwargs:
            where = {"entity_type": kwargs["entity_type"]}
        logger.info(
            "[认知服务] 搜索侧写: query_len=%s top_k=%s where=%s",
            len(query or ""),
            top_k,
            where or {},
        )
        results: list[dict[str, Any]] = await self._vector_store.query_profiles(
            query,
            top_k=top_k,
            where=where,
            reranker=self._reranker,
            candidate_multiplier=config.rerank_candidate_multiplier,
        )
        logger.info("[认知服务] 搜索侧写完成: count=%s", len(results))
        return results
