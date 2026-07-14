"""MemeService 检索与列表操作。"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any


from Undefined.attachments import AttachmentRecord
from Undefined.memes._image_utils import _now_iso
from Undefined.memes.models import (
    MemeRecord,
    MemeSearchItem,
)
from Undefined.utils.message_targets import resolve_delivery_address
from Undefined.utils.coerce import safe_int

if TYPE_CHECKING:
    import threading

    from Undefined.memes.store import MemeStore
    from Undefined.memes.vector_store import MemeVectorStore

logger = logging.getLogger(__name__)


class MemeSearchMixin:
    if TYPE_CHECKING:
        _cfg: Any
        _global_image_cache: dict[str, AttachmentRecord]
        _global_image_cache_lock: threading.Lock
        _job_queue: Any | None
        _retrieval_runtime: Any | None
        _store: MemeStore
        _vector_store: MemeVectorStore

    def resolve_global_image_sync(self, uid: str) -> AttachmentRecord | None:
        normalized_uid = str(uid or "").strip()
        if not normalized_uid:
            return None

        with self._global_image_cache_lock:
            cached = self._global_image_cache.get(normalized_uid)
        if cached is not None:
            return cached

        record = self._store.get_sync(normalized_uid)
        if record is None or not record.enabled or record.status != "ready":
            return None
        # scope_key 留空：表情库 UID 全局可解析，不受会话 scope 限制
        attachment = AttachmentRecord(
            uid=record.uid,
            scope_key="",
            kind="image",
            media_type="image",
            display_name=Path(record.blob_path).name,
            source_kind="meme_library",
            source_ref=Path(record.blob_path).resolve().as_uri(),
            local_path=record.blob_path,
            mime_type=record.mime_type,
            sha256=record.content_sha256,
            created_at=record.created_at,
            segment_data={"subType": "1"},
            semantic_kind="meme",
            description=record.description,
        )
        with self._global_image_cache_lock:
            self._global_image_cache[normalized_uid] = attachment
        return attachment

    async def resolve_global_image(self, uid: str) -> AttachmentRecord | None:
        return await asyncio.to_thread(self.resolve_global_image_sync, uid)

    async def get_meme(self, uid: str) -> dict[str, Any] | None:
        record = await self._store.get(uid)
        if record is None:
            return None
        sources = await self._store.get_sources(uid)
        return {
            "record": self.serialize_record(record),
            "sources": [source.__dict__ for source in sources],
        }

    async def get_record(self, uid: str) -> MemeRecord | None:
        return await self._store.get(uid)

    def serialize_record(self, record: MemeRecord) -> dict[str, Any]:
        preview_path = record.preview_path or record.blob_path
        return {
            "uid": record.uid,
            "description": record.description,
            "auto_description": record.auto_description,
            "manual_description": record.manual_description,
            "ocr_text": record.ocr_text,
            "tags": list(record.tags),
            "aliases": list(record.aliases),
            "enabled": bool(record.enabled),
            "pinned": bool(record.pinned),
            "is_animated": bool(record.is_animated),
            "mime_type": record.mime_type,
            "file_size": record.file_size,
            "width": record.width,
            "height": record.height,
            "blob_url": f"/api/v1/management/memes/{record.uid}/blob",
            "preview_url": f"/api/v1/management/memes/{record.uid}/preview",
            "use_count": record.use_count,
            "last_used_at": record.last_used_at,
            "created_at": record.created_at,
            "updated_at": record.updated_at,
            "status": record.status,
            "search_text": record.search_text,
            "preview_path": preview_path,
        }

    def serialize_list_item(self, record: MemeRecord) -> dict[str, Any]:
        return {
            "uid": record.uid,
            "description": record.description,
            "enabled": bool(record.enabled),
            "pinned": bool(record.pinned),
            "is_animated": bool(record.is_animated),
            "use_count": int(record.use_count),
            "created_at": record.created_at,
            "updated_at": record.updated_at,
            "status": record.status,
        }

    async def list_memes(
        self,
        *,
        query: str = "",
        enabled: bool | None = None,
        animated: bool | None = None,
        pinned: bool | None = None,
        sort: str = "updated_at",
        page: int = 1,
        page_size: int = 50,
        summary: bool = False,
    ) -> dict[str, Any]:
        items, total = await self._store.list_memes(
            query=query,
            enabled=enabled,
            animated=animated,
            pinned=pinned,
            sort=sort,
            page=page,
            page_size=page_size,
        )
        return {
            "ok": True,
            "total": total,
            "window_total": total,
            "total_exact": True,
            "page": max(1, int(page)),
            "page_size": max(1, min(200, int(page_size))),
            "has_more": max(1, int(page)) * max(1, min(200, int(page_size))) < total,
            "sort": str(sort or "updated_at"),
            "items": [
                self.serialize_list_item(item)
                if summary
                else self.serialize_record(item)
                for item in items
            ],
        }

    async def stats(self) -> dict[str, Any]:
        stats = await self._store.stats()
        cfg = self._cfg()
        stats["max_items"] = int(cfg.max_items)
        stats["max_total_bytes"] = int(cfg.max_total_bytes)
        queue = self._job_queue.snapshot() if self._job_queue is not None else None
        stats["queue"] = queue
        return stats

    async def search_memes(
        self,
        query: str,
        *,
        query_mode: str = "hybrid",
        keyword_query: str | None = None,
        semantic_query: str | None = None,
        top_k: int = 8,
        include_disabled: bool = False,
        sort: str = "relevance",
    ) -> dict[str, Any]:
        raw_query = str(query or "").strip()
        raw_keyword_query = str(keyword_query or "").strip()
        raw_semantic_query = str(semantic_query or "").strip()
        normalized_mode = str(query_mode or "hybrid").strip().lower()
        if normalized_mode not in {"keyword", "semantic", "hybrid"}:
            normalized_mode = "hybrid"
        resolved_keyword_query = raw_keyword_query or raw_query
        resolved_semantic_query = raw_semantic_query or raw_query
        if normalized_mode == "keyword" and not resolved_keyword_query:
            return {
                "ok": True,
                "count": 0,
                "query_mode": normalized_mode,
                "keyword_query": resolved_keyword_query,
                "semantic_query": resolved_semantic_query,
                "items": [],
            }
        if normalized_mode == "semantic" and not resolved_semantic_query:
            return {
                "ok": True,
                "count": 0,
                "query_mode": normalized_mode,
                "keyword_query": resolved_keyword_query,
                "semantic_query": resolved_semantic_query,
                "items": [],
            }
        if (
            normalized_mode == "hybrid"
            and not resolved_keyword_query
            and not resolved_semantic_query
        ):
            return {
                "ok": True,
                "count": 0,
                "query_mode": normalized_mode,
                "keyword_query": resolved_keyword_query,
                "semantic_query": resolved_semantic_query,
                "items": [],
            }

        cfg = self._cfg()
        keyword_hits: list[dict[str, Any]] = []
        if normalized_mode in {"keyword", "hybrid"} and resolved_keyword_query:
            keyword_hits = await self._store.search_keyword(
                resolved_keyword_query,
                limit=max(int(cfg.keyword_top_k), int(top_k)),
                include_disabled=include_disabled,
            )
        semantic_hits: list[dict[str, Any]] = []
        if normalized_mode in {"semantic", "hybrid"} and resolved_semantic_query:
            semantic_hits = await self._vector_store.query(
                resolved_semantic_query,
                top_k=max(int(cfg.semantic_top_k), int(top_k)),
                include_disabled=include_disabled,
            )
        merged: dict[str, dict[str, Any]] = {}

        for item in keyword_hits:
            record: MemeRecord = item["record"]
            merged[record.uid] = {
                "record": record,
                "keyword_score": float(item.get("keyword_score", 0.0)),
                "semantic_score": 0.0,
                "rerank_score": None,
            }

        missing_semantic_uids = [
            str(item.get("uid") or "").strip()
            for item in semantic_hits
            if str(item.get("uid") or "").strip()
            and str(item.get("uid") or "").strip() not in merged
        ]
        missing_records = (
            await self._store.get_many(missing_semantic_uids)
            if missing_semantic_uids
            else {}
        )

        for item in semantic_hits:
            uid = str(item.get("uid") or "").strip()
            if not uid:
                continue
            existing = merged.get(uid)
            if existing is None:
                stored_record = missing_records.get(uid)
                if stored_record is None:
                    continue
                existing = {
                    "record": stored_record,
                    "keyword_score": 0.0,
                    "semantic_score": 0.0,
                    "rerank_score": None,
                }
                merged[uid] = existing
            existing["semantic_score"] = max(
                float(existing.get("semantic_score", 0.0)),
                float(item.get("semantic_score", 0.0)),
            )

        reranker = (
            self._retrieval_runtime.ensure_reranker()
            if self._retrieval_runtime is not None
            else None
        )
        ranked_candidates = list(merged.values())
        rerank_query = resolved_semantic_query or resolved_keyword_query
        if (
            reranker is not None
            and normalized_mode in {"semantic", "hybrid"}
            and rerank_query
            and ranked_candidates
        ):
            documents = [
                candidate["record"].search_text for candidate in ranked_candidates
            ]
            reranked = await reranker.rerank(
                rerank_query,
                documents,
                top_n=min(len(documents), int(cfg.rerank_top_k)),
            )
            for item in reranked:
                try:
                    index = int(item.get("index"))
                except (TypeError, ValueError):
                    continue
                if index < 0 or index >= len(ranked_candidates):
                    continue
                ranked_candidates[index]["rerank_score"] = float(
                    item.get("relevance_score", 0.0) or 0.0
                )

        def _final_score(item: dict[str, Any]) -> float:
            rerank_score = item.get("rerank_score")
            if rerank_score is not None:
                return float(rerank_score)
            # hybrid 模式：keyword 与 semantic 取较高分
            return max(
                float(item.get("keyword_score", 0.0)),
                float(item.get("semantic_score", 0.0)),
            )

        normalized_sort = str(sort or "relevance").strip().lower()
        if normalized_sort == "use_count":
            ranked_candidates.sort(
                key=lambda item: (
                    item["record"].pinned,
                    item["record"].use_count,
                    item["record"].updated_at,
                    _final_score(item),
                ),
                reverse=True,
            )
        elif normalized_sort == "created_at":
            ranked_candidates.sort(
                key=lambda item: (
                    item["record"].pinned,
                    item["record"].created_at,
                    item["record"].updated_at,
                    _final_score(item),
                ),
                reverse=True,
            )
        elif normalized_sort == "updated_at":
            ranked_candidates.sort(
                key=lambda item: (
                    item["record"].pinned,
                    item["record"].updated_at,
                    item["record"].use_count,
                    _final_score(item),
                ),
                reverse=True,
            )
        else:
            ranked_candidates.sort(
                key=lambda item: (
                    _final_score(item),
                    item["record"].pinned,
                    item["record"].use_count,
                    item["record"].updated_at,
                ),
                reverse=True,
            )

        items: list[dict[str, Any]] = []
        for candidate in ranked_candidates[: max(1, int(top_k))]:
            record = candidate["record"]
            search_item = MemeSearchItem(
                uid=record.uid,
                description=record.description,
                tags=list(record.tags),
                aliases=list(record.aliases),
                enabled=bool(record.enabled),
                pinned=bool(record.pinned),
                is_animated=record.is_animated,
                created_at=record.created_at,
                updated_at=record.updated_at,
                score=round(_final_score(candidate), 6),
                keyword_score=round(float(candidate.get("keyword_score", 0.0)), 6),
                semantic_score=round(float(candidate.get("semantic_score", 0.0)), 6),
                rerank_score=(
                    round(float(candidate["rerank_score"]), 6)
                    if candidate.get("rerank_score") is not None
                    else None
                ),
                use_count=record.use_count,
            )
            items.append(search_item.__dict__)
        return {
            "ok": True,
            "count": len(items),
            "query_mode": normalized_mode,
            "keyword_query": resolved_keyword_query,
            "semantic_query": resolved_semantic_query,
            "sort": normalized_sort,
            "items": items,
        }

    async def send_meme_by_uid(self, uid: str, context: dict[str, Any]) -> str:
        record = await self._store.get(uid)
        if record is None or not record.enabled or record.status != "ready":
            return f"发送失败：未找到可用表情包 UID：{uid}"

        sender = context.get("sender")
        if sender is None:
            return "发送失败：当前上下文缺少 sender"

        tool_args = {
            "target_type": context.get("target_type"),
            "target_id": context.get("target_id"),
        }
        target, target_error = resolve_delivery_address(tool_args, context)
        if target_error or target is None:
            return f"发送失败：{target_error or '无法确定目标会话'}"
        local_path = Path(record.blob_path)
        if not local_path.is_file():
            return f"发送失败：表情包文件不存在：{uid}"
        file_uri = local_path.resolve().as_uri()
        cq_message = f"[CQ:image,file={file_uri},subType=1]"
        history_message = f"[图片 uid={record.uid} name={local_path.name}]"
        history_attachment = await self.resolve_global_image(uid)
        history_attachments = (
            [history_attachment.prompt_ref()]
            if history_attachment is not None
            else None
        )

        preferred_temp_group_id = safe_int(context.get("group_id")) or None
        send_address_message = getattr(sender, "send_address_message", None)
        if callable(send_address_message):
            sent_message_id = await send_address_message(
                target,
                cq_message,
                preferred_temp_group_id=preferred_temp_group_id,
                history_message=history_message,
                attachments=history_attachments,
            )
        elif target.channel == "group":
            sent_message_id = await sender.send_group_message(
                target.target_id,
                cq_message,
                history_message=history_message,
                attachments=history_attachments,
            )
        elif target.channel == "qq":
            sent_message_id = await sender.send_private_message(
                target.target_id,
                cq_message,
                preferred_temp_group_id=preferred_temp_group_id,
                history_message=history_message,
                attachments=history_attachments,
            )
        else:
            return "发送失败：当前 sender 不支持微信投递地址"

        now = _now_iso()
        updated_record = await self._store.increment_use(uid, now)
        if updated_record is not None:
            await self._vector_store.upsert(updated_record)
        if sent_message_id is not None:
            return f"表情包已发送（message_id={sent_message_id}）"
        return "表情包已发送"

    async def blob_path_for_uid(
        self, uid: str, *, preview: bool = False
    ) -> Path | None:
        record = await self._store.get(uid)
        if record is None:
            return None
        path_text = (
            record.preview_path if preview and record.preview_path else record.blob_path
        )
        path = Path(path_text)
        return path if path.is_file() else None
