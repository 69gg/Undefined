"""认知记忆服务实现。"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Callable, cast

from Undefined.context import RequestContext
from Undefined.cognitive.chroma_scheduler import (
    CHROMA_PRIORITY_FOREGROUND,
    CHROMA_PRIORITY_FOREGROUND_CRITICAL,
)
from Undefined.utils.coerce import safe_float
from Undefined.cognitive.service.helpers import (
    _build_profile_vector_payload,
    _compose_where,
    _current_profile_name,
    _event_base_score,
    _event_dedupe_key,
    _event_timestamp_epoch,
    _normalize_profile_tags,
    _parse_iso_to_epoch_seconds,
    _parse_profile_markdown,
    _resolve_auto_request_type,
    _serialize_profile_markdown,
)
from Undefined.cognitive.vector_store_compat import call_vector_store_method

if TYPE_CHECKING:
    from Undefined.knowledge.runtime import RetrievalRuntime

logger = logging.getLogger(__name__)


class CognitiveService:
    def __init__(
        self,
        config_getter: Callable[[], Any],
        vector_store: Any,
        job_queue: Any,
        profile_storage: Any,
        reranker: Any = None,
        retrieval_runtime: RetrievalRuntime | None = None,
    ) -> None:
        self._config_getter = config_getter
        self._vector_store = vector_store
        self._job_queue = job_queue
        self._profile_storage = profile_storage
        self._reranker = reranker
        self._retrieval_runtime = retrieval_runtime

    async def stop(self) -> None:
        stop = getattr(self._vector_store, "stop", None)
        if callable(stop):
            await stop()

    def _base_reranker(self) -> Any:
        if self._retrieval_runtime is not None:
            return self._retrieval_runtime.ensure_reranker()
        return self._reranker

    def _current_reranker(self) -> Any:
        config = self._config_getter()
        if not bool(getattr(config, "enable_rerank", True)):
            return None
        return self._base_reranker()

    async def _prepare_query_embedding(self, query: str) -> list[float] | None:
        embed_query = getattr(self._vector_store, "embed_query", None)
        if not callable(embed_query):
            return None
        try:
            result = await embed_query(query)
        except Exception as exc:
            logger.warning("[认知服务] 预生成查询向量失败，回退即时计算: error=%s", exc)
            return None
        if not isinstance(result, list):
            logger.warning("[认知服务] 预生成查询向量返回值非法，回退即时计算")
            return None
        normalized: list[float] = []
        for item in result:
            try:
                normalized.append(float(item))
            except (TypeError, ValueError):
                logger.warning("[认知服务] 预生成查询向量包含非法元素，回退即时计算")
                return None
        return normalized

    @property
    def enabled(self) -> bool:
        return bool(self._config_getter().enabled)

    async def sync_profile_display_name(
        self,
        *,
        entity_type: str,
        entity_id: str,
        preferred_name: str,
    ) -> bool:
        normalized_entity_type = str(entity_type or "").strip().lower()
        normalized_entity_id = str(entity_id or "").strip()
        normalized_name = str(preferred_name or "").strip()
        if normalized_entity_type not in {"user", "group"}:
            return False
        if not normalized_entity_id or not normalized_name:
            return False
        if self._profile_storage is None or self._vector_store is None:
            return False

        existing = await self._profile_storage.read_profile(
            normalized_entity_type,
            normalized_entity_id,
        )
        if not existing:
            return False

        parsed = _parse_profile_markdown(existing)
        if parsed is None:
            return False
        frontmatter, summary = parsed
        current_name = _current_profile_name(normalized_entity_type, frontmatter)
        if current_name == normalized_name:
            return False

        frontmatter["name"] = normalized_name
        frontmatter["updated_at"] = datetime.now().isoformat()
        if normalized_entity_type == "user":
            frontmatter["nickname"] = normalized_name
            frontmatter["qq"] = normalized_entity_id
        else:
            frontmatter["group_name"] = normalized_name
            frontmatter["group_id"] = normalized_entity_id

        updated_markdown = _serialize_profile_markdown(frontmatter, summary)
        await self._profile_storage.write_profile(
            normalized_entity_type,
            normalized_entity_id,
            updated_markdown,
        )

        profile_doc, profile_metadata = _build_profile_vector_payload(
            entity_type=normalized_entity_type,
            entity_id=normalized_entity_id,
            effective_name=normalized_name,
            tags=_normalize_profile_tags(frontmatter.get("tags")),
            summary=summary,
        )
        await call_vector_store_method(
            self._vector_store.upsert_profile,
            f"{normalized_entity_type}:{normalized_entity_id}",
            profile_doc,
            profile_metadata,
            priority=CHROMA_PRIORITY_FOREGROUND,
        )
        logger.info(
            "[认知服务] 已刷新侧写展示名: entity_type=%s entity_id=%s old=%s new=%s",
            normalized_entity_type,
            normalized_entity_id,
            current_name,
            normalized_name,
        )
        return True

    @staticmethod
    def _uid_candidates(user_id: str, sender_id: str) -> list[str]:
        values: list[str] = []
        for raw in (sender_id, user_id):
            text = str(raw or "").strip()
            if text and text not in values:
                values.append(text)
        return values

    @staticmethod
    def _merge_weighted_events(
        scoped_results: list[tuple[list[dict[str, Any]], float]],
        *,
        top_k: int,
        current_group_id: str = "",
        current_group_boost: float = 1.0,
    ) -> list[dict[str, Any]]:
        safe_top_k = max(1, int(top_k))
        safe_group_boost = max(0.0, float(current_group_boost))
        seen_keys: set[tuple[str, str, str, str, str, str]] = set()
        # 排序主键优先使用“作用域内原始排名”（已含 time_decay/mmr/rerank 效果），
        scored_items: list[
            tuple[float, float, float, float, float, int, dict[str, Any]]
        ] = []
        serial = 0
        for scoped_events, scope_weight in scoped_results:
            safe_scope_weight = max(0.0, safe_float(scope_weight, default=1.0))
            scope_size = max(1, len(scoped_events))
            for rank_idx, event in enumerate(scoped_events):
                dedupe_key = _event_dedupe_key(event)
                if dedupe_key in seen_keys:
                    continue
                seen_keys.add(dedupe_key)
                metadata = event.get("metadata")
                if not isinstance(metadata, dict):
                    metadata = {}
                scope_boost = safe_scope_weight
                if (
                    current_group_id
                    and str(metadata.get("group_id", "")).strip() == current_group_id
                ):
                    scope_boost *= safe_group_boost
                # 保留每个 scope 内已重排结果（time_decay/mmr/rerank）的相对顺序。
                rank_score = float(scope_size - rank_idx) / float(scope_size)
                weighted_rank_score = rank_score * scope_boost
                base_score = _event_base_score(event)
                weighted_score = base_score * scope_boost
                scored_items.append(
                    (
                        weighted_rank_score,
                        weighted_score,
                        rank_score,
                        base_score,
                        _event_timestamp_epoch(metadata),
                        serial,
                        event,
                    )
                )
                serial += 1
        scored_items.sort(
            key=lambda item: (
                -item[0],
                -item[1],
                -item[2],
                -item[3],
                -item[4],
                item[5],
            )
        )
        return [item[6] for item in scored_items[:safe_top_k]]

    @staticmethod
    def _merge_event_candidates(
        scoped_results: list[tuple[list[dict[str, Any]], float]],
        *,
        current_group_id: str = "",
        current_group_boost: float = 1.0,
    ) -> list[dict[str, Any]]:
        candidate_count = sum(len(events) for events, _ in scoped_results)
        if candidate_count <= 0:
            return []
        return CognitiveService._merge_weighted_events(
            scoped_results,
            top_k=candidate_count,
            current_group_id=current_group_id,
            current_group_boost=current_group_boost,
        )

    @staticmethod
    async def _rerank_events(
        *,
        reranker: Any,
        query: str,
        events: list[dict[str, Any]],
        top_k: int,
    ) -> list[dict[str, Any]]:
        safe_top_k = max(1, int(top_k))
        if not reranker or not events:
            return events[:safe_top_k]

        rerank_started = time.perf_counter()
        try:
            reranked = await reranker.rerank(
                query,
                [str(event.get("document", "")) for event in events],
                top_n=safe_top_k,
            )
        except Exception as exc:
            logger.warning(
                "[认知服务] 自动检索最终重排失败，回退融合排序: candidates=%s top_k=%s err=%s",
                len(events),
                safe_top_k,
                exc,
            )
            return events[:safe_top_k]

        ranked_events: list[dict[str, Any]] = []
        for item in reranked[:safe_top_k]:
            index = int(safe_float(item.get("index"), default=-1))
            if index < 0 or index >= len(events):
                continue
            event = dict(events[index])
            event["rerank_score"] = safe_float(item.get("relevance_score"), default=0.0)
            ranked_events.append(event)

        if not ranked_events:
            logger.warning(
                "[认知服务] 自动检索最终重排结果为空，回退融合排序: candidates=%s top_k=%s",
                len(events),
                safe_top_k,
            )
            return events[:safe_top_k]

        logger.info(
            "[认知服务] 自动检索最终重排完成: candidates=%s final=%s query_len=%s duration=%.3fs",
            len(events),
            len(ranked_events),
            len(query or ""),
            time.perf_counter() - rerank_started,
        )
        return ranked_events

    @staticmethod
    def _normalize_recall_queries(
        query: str, recall_queries: list[str] | None
    ) -> list[str]:
        normalized: list[str] = []
        for raw_query in recall_queries or []:
            text = str(raw_query or "").strip()
            if text:
                normalized.append(text)
        if normalized:
            return normalized
        fallback = str(query or "").strip()
        return [fallback] if fallback else []

    async def _query_events_for_auto_context(
        self,
        *,
        query: str,
        recall_queries: list[str] | None = None,
        request_type: str,
        group_id: str,
        user_id: str,
        sender_id: str,
        top_k: int,
        config: Any,
    ) -> list[dict[str, Any]]:
        safe_top_k = max(1, int(top_k))
        scope_candidate_multiplier = int(
            getattr(config, "auto_scope_candidate_multiplier", 2)
        )
        if scope_candidate_multiplier <= 0:
            scope_candidate_multiplier = 2
        scoped_top_k = max(safe_top_k, safe_top_k * scope_candidate_multiplier)
        current_group_boost = safe_float(
            getattr(config, "auto_current_group_boost", 1.15), default=1.15
        )
        if current_group_boost <= 0:
            current_group_boost = 1.15
        current_private_boost = safe_float(
            getattr(config, "auto_current_private_boost", 1.25), default=1.25
        )
        if current_private_boost <= 0:
            current_private_boost = 1.25
        normalized_recall_queries = self._normalize_recall_queries(
            query, recall_queries
        )
        if not normalized_recall_queries:
            return []
        configured_reranker = self._current_reranker()
        final_reranker = (
            configured_reranker if len(normalized_recall_queries) > 1 else None
        )
        query_level_reranker = (
            None if len(normalized_recall_queries) > 1 else configured_reranker
        )
        common_kwargs: dict[str, Any] = {
            "reranker": query_level_reranker,
            "candidate_multiplier": config.rerank_candidate_multiplier,
            "time_decay_enabled": bool(getattr(config, "time_decay_enabled", True)),
            "time_decay_half_life_days": float(
                getattr(config, "time_decay_half_life_days_auto", 14.0)
            ),
            "time_decay_boost": float(getattr(config, "time_decay_boost", 0.2)),
            "time_decay_min_similarity": float(
                getattr(config, "time_decay_min_similarity", 0.35)
            ),
            "apply_mmr": True,
        }
        uid_values = self._uid_candidates(user_id, sender_id)

        if request_type == "group":
            scoped_results: list[tuple[list[dict[str, Any]], float]] = []
            for recall_query in normalized_recall_queries:
                query_embedding = await self._prepare_query_embedding(recall_query)
                query_kwargs = dict(common_kwargs)
                if query_embedding is not None:
                    query_kwargs["query_embedding"] = query_embedding
                group_events = await call_vector_store_method(
                    self._vector_store.query_events,
                    recall_query,
                    priority=CHROMA_PRIORITY_FOREGROUND,
                    top_k=scoped_top_k,
                    where={"request_type": "group"},
                    **query_kwargs,
                )
                scoped_results.append((group_events, 1.0))
            merge_started = time.perf_counter()
            candidates = self._merge_event_candidates(
                scoped_results,
                current_group_id=group_id,
                current_group_boost=current_group_boost,
            )
            merged = await self._rerank_events(
                reranker=final_reranker,
                query=query,
                events=candidates,
                top_k=safe_top_k,
            )
            merge_duration = time.perf_counter() - merge_started
            logger.info(
                "[认知服务] 自动检索（群聊）: recall_queries=%s group_candidates=%s merged=%s top_k=%s scope_multiplier=%s current_group_boost=%.2f final_rerank=%s merge=%.3fs",
                len(normalized_recall_queries),
                len(candidates),
                len(merged),
                safe_top_k,
                scope_candidate_multiplier,
                current_group_boost,
                bool(final_reranker),
                merge_duration,
            )
            return merged

        if request_type == "private":
            scoped_results = []
            private_where: dict[str, Any] | None = None
            if uid_values:
                uid_clauses = [{"user_id": value} for value in uid_values] + [
                    {"sender_id": value} for value in uid_values
                ]
                private_where = {
                    "$and": [
                        {"request_type": "private"},
                        {"$or": uid_clauses},
                    ]
                }

            for recall_query in normalized_recall_queries:
                query_embedding = await self._prepare_query_embedding(recall_query)
                query_kwargs = dict(common_kwargs)
                if query_embedding is not None:
                    query_kwargs["query_embedding"] = query_embedding
                group_task = call_vector_store_method(
                    self._vector_store.query_events,
                    recall_query,
                    priority=CHROMA_PRIORITY_FOREGROUND,
                    top_k=scoped_top_k,
                    where={"request_type": "group"},
                    **query_kwargs,
                )
                if private_where is not None:
                    private_task = call_vector_store_method(
                        self._vector_store.query_events,
                        recall_query,
                        priority=CHROMA_PRIORITY_FOREGROUND,
                        top_k=scoped_top_k,
                        where=private_where,
                        **query_kwargs,
                    )
                    group_events_raw, private_events_raw = await asyncio.gather(
                        group_task, private_task
                    )
                    group_events = cast(list[dict[str, Any]], group_events_raw)
                    private_events = cast(list[dict[str, Any]], private_events_raw)
                else:
                    group_events = cast(list[dict[str, Any]], await group_task)
                    private_events = []
                scoped_results.append((group_events, 1.0))
                scoped_results.append((private_events, current_private_boost))
            merge_started = time.perf_counter()
            candidates = self._merge_event_candidates(scoped_results)
            merged = await self._rerank_events(
                reranker=final_reranker,
                query=query,
                events=candidates,
                top_k=safe_top_k,
            )
            merge_duration = time.perf_counter() - merge_started
            group_candidate_count = sum(
                len(events) for events, weight in scoped_results if weight == 1.0
            )
            private_candidate_count = sum(
                len(events)
                for events, weight in scoped_results
                if weight == current_private_boost
            )
            logger.info(
                "[认知服务] 自动检索（私聊）: recall_queries=%s group_candidates=%s private_candidates=%s candidates=%s merged=%s top_k=%s scope_multiplier=%s private_boost=%.2f uid_candidates=%s final_rerank=%s merge=%.3fs",
                len(normalized_recall_queries),
                group_candidate_count,
                private_candidate_count,
                len(candidates),
                len(merged),
                safe_top_k,
                scope_candidate_multiplier,
                current_private_boost,
                uid_values,
                bool(final_reranker),
                merge_duration,
            )
            return merged

        where: dict[str, Any] | None = None
        if group_id:
            where = {"group_id": group_id}
        elif uid_values:
            where = {
                "$or": [{"user_id": value} for value in uid_values]
                + [{"sender_id": value} for value in uid_values]
            }
        scoped_results = []
        for recall_query in normalized_recall_queries:
            query_embedding = await self._prepare_query_embedding(recall_query)
            query_kwargs = dict(common_kwargs)
            if query_embedding is not None:
                query_kwargs["query_embedding"] = query_embedding
            events = await call_vector_store_method(
                self._vector_store.query_events,
                recall_query,
                priority=CHROMA_PRIORITY_FOREGROUND,
                top_k=scoped_top_k,
                where=where,
                **query_kwargs,
            )
            scoped_results.append((events, 1.0))
        candidates = self._merge_event_candidates(scoped_results)
        merged = await self._rerank_events(
            reranker=final_reranker,
            query=query,
            events=candidates,
            top_k=safe_top_k,
        )
        logger.info(
            "[认知服务] 自动检索（兜底）: mode=%s recall_queries=%s where=%s candidates=%s merged=%s top_k=%s final_rerank=%s",
            request_type or "unknown",
            len(normalized_recall_queries),
            where or {},
            len(candidates),
            len(merged),
            safe_top_k,
            bool(final_reranker),
        )
        return merged

    async def enqueue_job(
        self,
        memo: str,
        observations: list[str],
        context: dict[str, Any],
        *,
        force: bool = False,
    ) -> str | None:
        memo_text = str(memo or "").strip()
        observation_items = (
            [s for s in observations if s.strip()] if observations else []
        )
        if not self.enabled:
            logger.info("[认知服务] 已禁用，跳过入队")
            return None
        if not memo_text and not observation_items:
            logger.info("[认知服务] memo/observations 均为空，跳过入队")
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
            safe_request_id = ""

        end_seq_raw = context.get("_end_seq", 0)
        try:
            end_seq = int(end_seq_raw)
        except (TypeError, ValueError):
            end_seq = 0

        has_observations = bool(observation_items)
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
        source_message = str(context.get("historian_source_message") or "").strip()
        recent_messages_raw = context.get("historian_recent_messages", [])
        recent_messages: list[str] = []
        if isinstance(recent_messages_raw, list):
            recent_messages = [
                str(item).strip() for item in recent_messages_raw if str(item).strip()
            ]

        profile_targets: list[dict[str, str]] = []
        if has_observations:
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
            "memo": memo_text,
            "observations": observation_items,
            "has_observations": has_observations,
            "perspective": perspective,
            "profile_targets": profile_targets,
            "schema_version": "final_v1",
            "source_message": source_message,
            "recent_messages": recent_messages,
            "force": bool(force),
        }
        logger.info(
            "[认知服务] 准备入队: request_id=%s end_seq=%s user=%s group=%s sender=%s perspective=%s has_observations=%s profile_targets=%s memo_len=%s observations_len=%s source_len=%s recent_ref=%s force=%s",
            job.get("request_id", ""),
            job.get("end_seq", 0),
            job.get("user_id", ""),
            job.get("group_id", ""),
            job.get("sender_id", ""),
            perspective or "default",
            has_observations,
            len(profile_targets),
            len(memo_text),
            len(observation_items),
            len(source_message),
            len(recent_messages),
            bool(force),
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
        request_type: str | None = None,
        recall_queries: list[str] | None = None,
    ) -> str:
        config = self._config_getter()
        safe_group_id = str(group_id or "").strip()
        safe_user_id = str(user_id or "").strip()
        safe_sender_id = str(sender_id or "").strip()
        safe_request_type = _resolve_auto_request_type(
            request_type=request_type,
            group_id=safe_group_id,
            user_id=safe_user_id,
            sender_id=safe_sender_id,
        )
        parts: list[str] = []
        logger.info(
            "[认知服务] 构建上下文: query_len=%s type=%s user=%s sender=%s group=%s top_k=%s",
            len(query or ""),
            safe_request_type or "",
            safe_user_id,
            safe_sender_id,
            safe_group_id,
            getattr(config, "auto_top_k", 5),
        )

        uid = safe_sender_id or safe_user_id
        if uid:
            profile = await self._profile_storage.read_profile("user", uid)
            if profile:
                label = f"{sender_name}（UID: {uid}）" if sender_name else f"UID: {uid}"
                parts.append(f"## 用户侧写 — {label}\n{profile}")

        if safe_group_id:
            gprofile = await self._profile_storage.read_profile("group", safe_group_id)
            if gprofile:
                glabel = (
                    f"{group_name}（GID: {safe_group_id}）"
                    if group_name
                    else f"GID: {safe_group_id}"
                )
                parts.append(f"## 群聊侧写 — {glabel}\n{gprofile}")

        default_top_k = 5
        try:
            top_k = int(getattr(config, "auto_top_k", default_top_k))
        except Exception:
            top_k = default_top_k
        if top_k <= 0:
            top_k = default_top_k
        top_k = min(top_k, 500)
        try:
            events = await self._query_events_for_auto_context(
                query=query,
                recall_queries=recall_queries,
                request_type=safe_request_type,
                group_id=safe_group_id,
                user_id=safe_user_id,
                sender_id=safe_sender_id,
                top_k=top_k,
                config=config,
            )
        except Exception as exc:
            logger.warning(
                "[认知服务] 自动上下文事件检索失败，降级为空结果: type=%s user=%s sender=%s group=%s err=%s",
                safe_request_type,
                safe_user_id,
                safe_sender_id,
                safe_group_id,
                exc,
            )
            events = []
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
            "这部分属于认知记忆（cognitive.* / end.observations），不同于 memory.* 手动长期记忆。 -->\n"
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
        if time_from_epoch is not None:
            where_clauses.append({"timestamp_epoch": {"$gte": time_from_epoch}})
        if time_to_epoch is not None:
            where_clauses.append({"timestamp_epoch": {"$lte": time_to_epoch}})

        where = _compose_where(where_clauses)
        default_top_k = getattr(config, "tool_default_top_k", 12)
        top_k_raw = kwargs.get("top_k", default_top_k)
        try:
            top_k = int(top_k_raw)
        except Exception:
            top_k = default_top_k
        if top_k <= 0:
            top_k = default_top_k
        top_k = min(top_k, 500)
        logger.info(
            "[认知服务] 搜索事件: query_len=%s top_k=%s where=%s time_from=%s time_to=%s",
            len(query or ""),
            top_k,
            where or {},
            time_from_epoch,
            time_to_epoch,
        )
        results = await call_vector_store_method(
            self._vector_store.query_events,
            query,
            priority=CHROMA_PRIORITY_FOREGROUND_CRITICAL,
            top_k=top_k,
            where=where or None,
            reranker=self._current_reranker(),
            candidate_multiplier=config.rerank_candidate_multiplier,
            time_decay_enabled=bool(getattr(config, "time_decay_enabled", True)),
            time_decay_half_life_days=float(
                getattr(config, "time_decay_half_life_days_tool", 60.0)
            ),
            time_decay_boost=float(getattr(config, "time_decay_boost", 0.2)),
            time_decay_min_similarity=float(
                getattr(config, "time_decay_min_similarity", 0.35)
            ),
            apply_mmr=True,
            query_embedding=await self._prepare_query_embedding(query),
        )
        logger.info("[认知服务] 搜索事件完成: count=%s", len(results))
        return cast(list[dict[str, Any]], results)

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
        default_top_k = int(getattr(config, "profile_top_k", 5))
        top_k_raw = kwargs.get("top_k", default_top_k)
        try:
            top_k = int(top_k_raw)
        except Exception:
            top_k = default_top_k
        if top_k <= 0:
            top_k = default_top_k
        top_k = min(top_k, 500)

        where: dict[str, Any] | None = None
        entity_type_raw = kwargs.get("entity_type")
        entity_type = (
            str(entity_type_raw).strip() if entity_type_raw is not None else ""
        )
        if entity_type:
            where = {"entity_type": entity_type}

        logger.info(
            "[认知服务] 搜索侧写: query_len=%s top_k=%s where=%s",
            len(query or ""),
            top_k,
            where or {},
        )
        results = await call_vector_store_method(
            self._vector_store.query_profiles,
            query,
            priority=CHROMA_PRIORITY_FOREGROUND_CRITICAL,
            top_k=top_k,
            where=where,
            reranker=self._current_reranker(),
            candidate_multiplier=config.rerank_candidate_multiplier,
            query_embedding=await self._prepare_query_embedding(query),
        )
        logger.info("[认知服务] 搜索侧写完成: count=%s", len(results))
        return cast(list[dict[str, Any]], results)
