from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime
import hashlib
import logging
import mimetypes
from pathlib import Path
import re
import shutil
import threading
from typing import Any
from uuid import uuid4

from PIL import Image

from Undefined.attachments import AttachmentRecord
from Undefined.memes.models import (
    MemeRecord,
    MemeSearchItem,
    MemeSourceRecord,
    build_search_text,
    normalize_string_list,
)
from Undefined.memes.store import MemeStore
from Undefined.memes.vector_store import MemeVectorStore
from Undefined.utils.message_targets import resolve_message_target
from Undefined.utils.paths import ensure_dir

logger = logging.getLogger(__name__)

_IMAGE_EXTENSIONS_BY_MIME = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/bmp": ".bmp",
    "image/svg+xml": ".svg",
}
_TAG_SPLIT_RE = re.compile(r"[,，\n]+")


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _safe_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _guess_suffix(path: Path, mime_type: str) -> str:
    suffix = path.suffix.lower()
    if suffix:
        return suffix
    guessed = _IMAGE_EXTENSIONS_BY_MIME.get(mime_type)
    if guessed:
        return guessed
    mime_guess = mimetypes.guess_extension(mime_type or "")
    if mime_guess:
        return mime_guess.lower()
    return ".bin"


def _normalize_tags(raw_tags: list[str] | str | None) -> list[str]:
    if raw_tags is None:
        return []
    if isinstance(raw_tags, str):
        parts = [part.strip() for part in _TAG_SPLIT_RE.split(raw_tags)]
        return normalize_string_list(parts)
    return normalize_string_list(raw_tags)


@dataclass
class _IngestDigestLockEntry:
    lock: asyncio.Lock
    users: int = 0


class MemeService:
    def __init__(
        self,
        *,
        config_getter: Any,
        store: MemeStore,
        vector_store: MemeVectorStore,
        job_queue: Any | None = None,
        ai_client: Any | None = None,
        attachment_registry: Any | None = None,
        retrieval_runtime: Any | None = None,
    ) -> None:
        self._config_getter = config_getter
        self._store = store
        self._vector_store = vector_store
        self._job_queue = job_queue
        self._ai_client = ai_client
        self._attachment_registry = attachment_registry
        self._retrieval_runtime = retrieval_runtime
        # Serialize same-content ingest jobs within the process to avoid duplicates.
        self._ingest_digest_locks: dict[str, _IngestDigestLockEntry] = {}
        self._ingest_digest_locks_guard = asyncio.Lock()
        self._global_image_cache: dict[str, AttachmentRecord] = {}
        self._global_image_cache_lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        cfg = self._config_getter()
        return bool(getattr(cfg, "enabled", False))

    @property
    def default_query_mode(self) -> str:
        mode = (
            str(
                getattr(self._config_getter(), "query_default_mode", "hybrid")
                or "hybrid"
            )
            .strip()
            .lower()
        )
        return mode if mode in {"keyword", "semantic", "hybrid"} else "hybrid"

    def _cfg(self) -> Any:
        return self._config_getter()

    def _blob_dir(self) -> Path:
        return ensure_dir(Path(self._cfg().blob_dir))

    async def _acquire_ingest_digest_lock(self, digest: str) -> _IngestDigestLockEntry:
        async with self._ingest_digest_locks_guard:
            entry = self._ingest_digest_locks.get(digest)
            if entry is None:
                entry = _IngestDigestLockEntry(lock=asyncio.Lock())
                self._ingest_digest_locks[digest] = entry
            entry.users += 1
        try:
            await entry.lock.acquire()
        except BaseException:
            await self._release_ingest_digest_lock_reference(digest, entry)
            raise
        return entry

    async def _release_ingest_digest_lock_reference(
        self,
        digest: str,
        entry: _IngestDigestLockEntry,
        *,
        release_lock: bool = False,
    ) -> None:
        if release_lock and entry.lock.locked():
            entry.lock.release()
        async with self._ingest_digest_locks_guard:
            entry.users = max(0, entry.users - 1)
            current = self._ingest_digest_locks.get(digest)
            if current is entry and entry.users == 0 and not entry.lock.locked():
                self._ingest_digest_locks.pop(digest, None)

    def _preview_dir(self) -> Path:
        return ensure_dir(Path(self._cfg().preview_dir))

    def _queue_enabled(self) -> bool:
        return self._job_queue is not None

    def _invalidate_global_image_cache(self, uid: str) -> None:
        normalized_uid = str(uid or "").strip()
        if not normalized_uid:
            return
        with self._global_image_cache_lock:
            self._global_image_cache.pop(normalized_uid, None)

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

    async def update_meme(
        self,
        uid: str,
        *,
        manual_description: str | None = None,
        tags: list[str] | str | None = None,
        aliases: list[str] | str | None = None,
        enabled: bool | None = None,
        pinned: bool | None = None,
    ) -> dict[str, Any] | None:
        record = await self._store.get(uid)
        if record is None:
            return None

        next_tags = list(record.tags) if tags is None else _normalize_tags(tags)
        next_aliases = (
            list(record.aliases) if aliases is None else _normalize_tags(aliases)
        )
        next_manual = (
            record.manual_description
            if manual_description is None
            else str(manual_description or "").strip()
        )
        next_enabled = record.enabled if enabled is None else bool(enabled)
        next_pinned = record.pinned if pinned is None else bool(pinned)
        next_search_text = build_search_text(
            manual_description=next_manual,
            auto_description=record.auto_description,
            ocr_text="",
            tags=next_tags,
            aliases=next_aliases,
        )

        updated = await self._store.update_fields(
            uid,
            {
                "manual_description": next_manual,
                "tags_json": next_tags,
                "aliases_json": next_aliases,
                "enabled": next_enabled,
                "pinned": next_pinned,
                "search_text": next_search_text,
                "updated_at": _now_iso(),
            },
        )
        if updated is None:
            return None
        self._invalidate_global_image_cache(uid)
        await self._vector_store.upsert(updated)
        return self.serialize_record(updated)

    async def delete_meme(self, uid: str) -> bool:
        record = await self._store.delete(uid)
        if record is None:
            return False
        self._invalidate_global_image_cache(uid)
        await self._vector_store.delete(uid)
        await asyncio.to_thread(self._delete_file_if_exists, Path(record.blob_path))
        if record.preview_path and record.preview_path != record.blob_path:
            await asyncio.to_thread(
                self._delete_file_if_exists,
                Path(record.preview_path),
            )
        return True

    def _delete_file_if_exists(self, path: Path) -> None:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            logger.debug("[memes] 删除文件失败: path=%s", path, exc_info=True)

    async def _cleanup_meme_artifacts(
        self,
        *,
        uid: str | None,
        blob_path: Path,
        preview_path: Path | None,
    ) -> None:
        if uid:
            try:
                await self._store.delete(uid)
                self._invalidate_global_image_cache(uid)
            except Exception:
                logger.exception(
                    "[memes] 清理记录失败: uid=%s",
                    uid,
                )
            try:
                await self._vector_store.delete(uid)
            except Exception:
                logger.exception(
                    "[memes] 清理向量索引失败: uid=%s",
                    uid,
                )
        await asyncio.to_thread(self._delete_file_if_exists, blob_path)
        if preview_path is not None and preview_path != blob_path:
            await asyncio.to_thread(self._delete_file_if_exists, preview_path)

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
        target, target_error = resolve_message_target(tool_args, context)
        if target_error or target is None:
            return f"发送失败：{target_error or '无法确定目标会话'}"
        target_type, target_id = target

        local_path = Path(record.blob_path)
        if not local_path.is_file():
            return f"发送失败：表情包文件不存在：{uid}"
        file_uri = local_path.resolve().as_uri()
        cq_message = f"[CQ:image,file={file_uri},subType=1]"
        history_message = f"[图片 uid={record.uid} name={local_path.name}]"
        history_attachment = self.resolve_global_image_sync(uid)
        history_attachments = (
            [history_attachment.prompt_ref()]
            if history_attachment is not None
            else None
        )

        if target_type == "group":
            sent_message_id = await sender.send_group_message(
                int(target_id),
                cq_message,
                history_message=history_message,
                attachments=history_attachments,
            )
        else:
            preferred_temp_group_id = _safe_int(context.get("group_id"))
            sent_message_id = await sender.send_private_message(
                int(target_id),
                cq_message,
                preferred_temp_group_id=preferred_temp_group_id,
                history_message=history_message,
                attachments=history_attachments,
            )

        now = _now_iso()
        updated_record = await self._store.increment_use(uid, now)
        if updated_record is not None:
            await self._vector_store.upsert(updated_record)
        if sent_message_id is not None:
            return f"表情包已发送（message_id={sent_message_id}）"
        return "表情包已发送"

    async def enqueue_incoming_attachments(
        self,
        *,
        attachments: list[dict[str, str]],
        chat_type: str,
        chat_id: int,
        sender_id: int,
        message_id: int | None,
        scope_key: str,
    ) -> None:
        if not self.enabled or not self._queue_enabled():
            return
        cfg = self._cfg()
        if chat_type == "group" and not bool(cfg.auto_ingest_group):
            return
        if chat_type == "private" and not bool(cfg.auto_ingest_private):
            return

        for item in attachments:
            media_type = str(item.get("media_type") or item.get("kind") or "").strip()
            uid = str(item.get("uid") or "").strip()
            if media_type != "image" or not uid:
                continue
            job = {
                "request_id": f"meme_ingest_{uid}",
                "kind": "ingest",
                "attachment_uid": uid,
                "scope_key": scope_key,
                "chat_type": chat_type,
                "chat_id": str(chat_id),
                "sender_id": str(sender_id),
                "message_id": str(message_id or ""),
                "queued_at": _now_iso(),
            }
            queue = self._job_queue
            if queue is None:
                return
            await queue.enqueue(job)

    async def enqueue_reanalyze(self, uid: str) -> str | None:
        if not self._queue_enabled():
            return None
        queue = self._job_queue
        if queue is None:
            return None
        result = await queue.enqueue(
            {
                "request_id": f"meme_reanalyze_{uid}",
                "kind": "reanalyze",
                "uid": uid,
                "queued_at": _now_iso(),
            }
        )
        return str(result)

    async def enqueue_reindex(self, uid: str) -> str | None:
        if not self._queue_enabled():
            return None
        queue = self._job_queue
        if queue is None:
            return None
        result = await queue.enqueue(
            {
                "request_id": f"meme_reindex_{uid}",
                "kind": "reindex",
                "uid": uid,
                "queued_at": _now_iso(),
            }
        )
        return str(result)

    async def process_job(self, job: Mapping[str, Any]) -> None:
        kind = str(job.get("kind") or "").strip().lower()
        if kind == "ingest":
            await self._process_ingest_job(job)
            return
        if kind == "reanalyze":
            await self._process_reanalyze_job(job)
            return
        if kind == "reindex":
            await self._process_reindex_job(job)
            return
        raise ValueError(f"unsupported meme job kind: {kind}")

    async def _process_reindex_job(self, job: Mapping[str, Any]) -> None:
        uid = str(job.get("uid") or "").strip()
        if not uid:
            return
        record = await self._store.get(uid)
        if record is None:
            return
        await self._vector_store.upsert(record)

    async def _process_reanalyze_job(self, job: Mapping[str, Any]) -> None:
        uid = str(job.get("uid") or "").strip()
        if not uid:
            return
        record = await self._store.get(uid)
        if record is None:
            return
        if self._ai_client is None:
            raise RuntimeError("reanalyze requires ai_client")
        try:
            judgement = await self._ai_client.judge_meme_image(record.blob_path)
        except Exception as exc:
            logger.exception(
                "[memes] judge stage failed during reanalyze: uid=%s err=%s", uid, exc
            )
            return
        if not bool(judgement.get("is_meme", False)):
            await self.delete_meme(uid)
            return
        try:
            described = await self._ai_client.describe_meme_image(record.blob_path)
        except Exception as exc:
            logger.exception(
                "[memes] describe stage failed during reanalyze: uid=%s err=%s",
                uid,
                exc,
            )
            return
        auto_description = str(described.get("description") or "").strip()
        next_tags = _normalize_tags(described.get("tags"))
        if not auto_description and not next_tags:
            logger.warning(
                "[memes] reanalyze describe failed, skip update: uid=%s", uid
            )
            return
        next_record = replace(
            record,
            auto_description=auto_description,
            ocr_text="",
            tags=next_tags,
            search_text=build_search_text(
                manual_description=record.manual_description,
                auto_description=auto_description,
                ocr_text="",
                tags=next_tags,
                aliases=record.aliases,
            ),
            updated_at=_now_iso(),
        )
        saved = await self._store.upsert_record(next_record)
        self._invalidate_global_image_cache(saved.uid)
        await self._vector_store.upsert(saved)

    async def _process_ingest_job(self, job: Mapping[str, Any]) -> None:
        if self._attachment_registry is None:
            raise RuntimeError("ingest requires attachment_registry")
        if self._ai_client is None:
            raise RuntimeError("ingest requires ai_client")

        attachment_uid = str(job.get("attachment_uid") or "").strip()
        scope_key = str(job.get("scope_key") or "").strip() or None
        if not attachment_uid:
            return
        attachment = self._attachment_registry.resolve(attachment_uid, scope_key)
        if attachment is None:
            raise FileNotFoundError(f"attachment uid unavailable: {attachment_uid}")
        if str(attachment.media_type).lower() != "image":
            return
        source_path = Path(str(attachment.local_path or ""))
        if not source_path.is_file():
            raise FileNotFoundError(source_path)
        file_size = source_path.stat().st_size
        cfg = self._cfg()
        if file_size > int(cfg.max_source_image_bytes):
            logger.info(
                "[memes] skip oversized image: uid=%s size=%s limit=%s",
                attachment_uid,
                file_size,
                cfg.max_source_image_bytes,
            )
            return

        digest = await asyncio.to_thread(self._hash_file, source_path)
        digest_lock_entry = await self._acquire_ingest_digest_lock(digest)
        try:
            existing = await self._store.find_by_sha256(digest)
            if existing is not None and not Path(existing.blob_path).is_file():
                logger.warning(
                    "[memes] 检测到孤儿记录，删除后重新入库: uid=%s blob_path=%s",
                    existing.uid,
                    existing.blob_path,
                )
                await self._cleanup_meme_artifacts(
                    uid=existing.uid,
                    blob_path=Path(existing.blob_path),
                    preview_path=(
                        Path(existing.preview_path) if existing.preview_path else None
                    ),
                )
                existing = await self._store.find_by_sha256(digest)
                if existing is not None and not Path(existing.blob_path).is_file():
                    raise RuntimeError(
                        f"stale meme record cleanup failed: uid={existing.uid}"
                    )
            source = MemeSourceRecord(
                uid=existing.uid if existing is not None else "",
                source_type="message_attachment",
                chat_type=str(job.get("chat_type") or ""),
                chat_id=str(job.get("chat_id") or ""),
                sender_id=str(job.get("sender_id") or ""),
                message_id=str(job.get("message_id") or ""),
                attachment_uid=attachment_uid,
                source_url=str(attachment.source_ref or ""),
                seen_at=_now_iso(),
            )
            if existing is not None:
                await self._store.add_source(replace(source, uid=existing.uid))
                await self._vector_store.upsert(existing)
                return

            with Image.open(source_path) as image:
                width, height = image.size
                is_animated = bool(getattr(image, "is_animated", False))
            if is_animated and not bool(cfg.allow_gif):
                return

            uid = await self._generate_uid()
            suffix = _guess_suffix(source_path, str(attachment.mime_type or ""))
            blob_path = self._blob_dir() / f"{uid}{suffix}"
            cleanup_preview_path = (
                self._preview_dir() / f"{uid}.png" if is_animated else blob_path
            )
            persisted_uid: str | None = None

            try:
                preview_path = await self._prepare_blob_and_preview(
                    source_path=source_path,
                    target_uid=uid,
                    suffix=suffix,
                    is_animated=is_animated,
                )
                if preview_path is not None:
                    cleanup_preview_path = preview_path
                mime_type = str(
                    attachment.mime_type
                    or mimetypes.guess_type(source_path.name)[0]
                    or "application/octet-stream"
                )
                analyze_path = str(
                    preview_path if preview_path is not None else blob_path
                )
                try:
                    judgement = await self._ai_client.judge_meme_image(analyze_path)
                except Exception as exc:
                    logger.exception(
                        "[memes] judge stage failed, treat as non-meme: uid=%s err=%s",
                        uid,
                        exc,
                    )
                    judgement = {"is_meme": False}
                if not bool(judgement.get("is_meme", False)):
                    await self._cleanup_meme_artifacts(
                        uid=None,
                        blob_path=blob_path,
                        preview_path=cleanup_preview_path,
                    )
                    return

                try:
                    described = await self._ai_client.describe_meme_image(analyze_path)
                except Exception as exc:
                    logger.exception(
                        "[memes] describe stage failed, drop uid=%s err=%s", uid, exc
                    )
                    described = {"description": "", "tags": []}
                tags = _normalize_tags(described.get("tags"))
                auto_description = str(described.get("description") or "").strip()
                if not auto_description and not tags:
                    logger.warning(
                        "[memes] describe stage returned empty result, drop uid=%s", uid
                    )
                    await self._cleanup_meme_artifacts(
                        uid=None,
                        blob_path=blob_path,
                        preview_path=cleanup_preview_path,
                    )
                    return
                now = _now_iso()
                record = MemeRecord(
                    uid=uid,
                    content_sha256=digest,
                    blob_path=str(blob_path),
                    preview_path=(
                        str(preview_path) if preview_path is not None else None
                    ),
                    mime_type=mime_type,
                    file_size=file_size,
                    width=width,
                    height=height,
                    is_animated=is_animated,
                    enabled=True,
                    pinned=False,
                    auto_description=auto_description,
                    manual_description="",
                    ocr_text="",
                    tags=tags,
                    aliases=[],
                    search_text=build_search_text(
                        manual_description="",
                        auto_description=auto_description,
                        ocr_text="",
                        tags=tags,
                        aliases=[],
                    ),
                    use_count=0,
                    last_used_at="",
                    created_at=now,
                    updated_at=now,
                    status="ready",
                    segment_data={"subType": "1"},
                )
                saved = await self._store.upsert_record(record)
                self._invalidate_global_image_cache(saved.uid)
                persisted_uid = saved.uid
                await self._store.add_source(replace(source, uid=saved.uid))
                await self._vector_store.upsert(saved)
            except Exception:
                await self._cleanup_meme_artifacts(
                    uid=persisted_uid,
                    blob_path=blob_path,
                    preview_path=cleanup_preview_path,
                )
                raise
        finally:
            await self._release_ingest_digest_lock_reference(
                digest,
                digest_lock_entry,
                release_lock=True,
            )
        await self._prune_if_needed()

    async def _prepare_blob_and_preview(
        self,
        *,
        source_path: Path,
        target_uid: str,
        suffix: str,
        is_animated: bool,
    ) -> Path | None:
        blob_path = self._blob_dir() / f"{target_uid}{suffix}"

        def _copy() -> None:
            shutil.copy2(source_path, blob_path)

        await asyncio.to_thread(_copy)
        if not is_animated:
            return blob_path

        preview_path = self._preview_dir() / f"{target_uid}.png"

        def _render_preview() -> None:
            with Image.open(source_path) as image:
                image.seek(0)
                frame = image.convert("RGBA")
                frame.save(preview_path, format="PNG")

        await asyncio.to_thread(_render_preview)
        return preview_path

    def _hash_file(self, path: Path) -> str:
        hasher = hashlib.sha256()
        with path.open("rb") as handle:
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                hasher.update(chunk)
        return hasher.hexdigest()

    async def _generate_uid(self) -> str:
        while True:
            candidate = f"pic_{uuid4().hex[:8]}"
            if await self._store.get(candidate) is not None:
                continue
            if (
                self._attachment_registry is not None
                and self._attachment_registry.get(candidate) is not None
            ):
                continue
            return candidate

    async def _prune_if_needed(self) -> None:
        stats = await self._store.stats()
        cfg = self._cfg()
        total_count = int(stats.get("total_count", 0))
        total_bytes = int(stats.get("total_bytes", 0))
        if total_count <= int(cfg.max_items) and total_bytes <= int(
            cfg.max_total_bytes
        ):
            return
        candidates = await self._store.list_prune_candidates()
        for candidate in candidates:
            if candidate.pinned:
                continue
            if total_count <= int(cfg.max_items) and total_bytes <= int(
                cfg.max_total_bytes
            ):
                break
            deleted = await self._store.delete(candidate.uid)
            if deleted is None:
                continue
            self._invalidate_global_image_cache(candidate.uid)
            await self._vector_store.delete(candidate.uid)
            await asyncio.to_thread(
                self._delete_file_if_exists, Path(deleted.blob_path)
            )
            if deleted.preview_path and deleted.preview_path != deleted.blob_path:
                await asyncio.to_thread(
                    self._delete_file_if_exists,
                    Path(deleted.preview_path),
                )
            total_count -= 1
            total_bytes -= int(deleted.file_size)

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
