"""认知记忆服务门面。"""

from __future__ import annotations

from typing import Any, Callable

from Undefined.context import RequestContext


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
        self, action_summary: str, new_info: str, context: dict[str, Any]
    ) -> str | None:
        if not self.enabled:
            return None
        ctx = RequestContext.current()
        from datetime import datetime, timezone

        now = datetime.now()
        job: dict[str, Any] = {
            "request_id": ctx.request_id if ctx else "",
            "user_id": str(ctx.user_id or "") if ctx else "",
            "group_id": str(ctx.group_id or "") if ctx else "",
            "sender_id": str(ctx.sender_id or "") if ctx else "",
            "request_type": ctx.request_type if ctx else "",
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "timestamp_local": now.isoformat(),
            "action_summary": action_summary,
            "new_info": new_info,
            "has_new_info": bool(new_info),
        }
        result: str | None = await self._job_queue.enqueue(job)
        return result

    async def build_context(
        self,
        query: str,
        group_id: str | None = None,
        user_id: str | None = None,
        sender_id: str | None = None,
    ) -> str:
        config = self._config_getter()
        parts: list[str] = []

        # 用户侧写
        uid = user_id or sender_id
        if uid:
            profile = await self._profile_storage.read_profile("user", uid)
            if profile:
                parts.append(f"## 用户侧写\n{profile}")

        # 群聊侧写
        if group_id:
            gprofile = await self._profile_storage.read_profile("group", group_id)
            if gprofile:
                parts.append(f"## 群聊侧写\n{gprofile}")

        # 相关事件
        where: dict[str, Any] | None = None
        if group_id:
            where = {"group_id": group_id}
        elif uid:
            where = {"user_id": uid}

        top_k = getattr(config, "auto_top_k", 5)
        events = await self._vector_store.query_events(
            query, top_k=top_k, where=where, reranker=self._reranker
        )
        if events:
            event_lines = "\n".join(
                f"- [{e['metadata'].get('timestamp_local', '')}] {e['document']}"
                for e in events
            )
            parts.append(f"## 相关记忆\n{event_lines}")

        return "\n\n".join(parts)

    async def search_events(self, query: str, **kwargs: Any) -> list[dict[str, Any]]:
        where: dict[str, Any] | None = None
        if "group_id" in kwargs or "user_id" in kwargs:
            where = {
                k: v
                for k, v in kwargs.items()
                if k in ("group_id", "user_id", "sender_id") and v
            }
        top_k = kwargs.get("top_k", 5)
        results: list[dict[str, Any]] = await self._vector_store.query_events(
            query, top_k=top_k, where=where or None, reranker=self._reranker
        )
        return results

    async def get_profile(self, entity_type: str, entity_id: str) -> str | None:
        result: str | None = await self._profile_storage.read_profile(
            entity_type, entity_id
        )
        return result

    async def search_profiles(self, query: str, **kwargs: Any) -> list[dict[str, Any]]:
        top_k = kwargs.get("top_k", 5)
        where: dict[str, Any] | None = None
        if "entity_type" in kwargs:
            where = {"entity_type": kwargs["entity_type"]}
        results: list[dict[str, Any]] = await self._vector_store.query_profiles(
            query, top_k=top_k, where=where, reranker=self._reranker
        )
        return results
