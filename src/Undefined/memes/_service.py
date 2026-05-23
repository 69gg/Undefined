"""MemeService 门面类。"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
import threading
from typing import Any


from Undefined.attachments import AttachmentRecord
from Undefined.memes._image_utils import (
    _normalize_tags,
    _now_iso,
)
from Undefined.memes.models import (
    IngestDigestLockEntry,
    build_search_text,
)
from Undefined.memes.store import MemeStore
from Undefined.memes.vector_store import MemeVectorStore
from Undefined.utils.paths import ensure_dir
from Undefined.memes.ingest import MemeIngestMixin
from Undefined.memes.search import MemeSearchMixin

logger = logging.getLogger(__name__)


class MemeService(MemeSearchMixin, MemeIngestMixin):
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
        # 同内容 digest 锁：进程内串行入库，防止重复 AI 分析
        self._ingest_digest_locks: dict[str, IngestDigestLockEntry] = {}
        self._ingest_digest_locks_guard = asyncio.Lock()
        self._global_image_cache: dict[str, AttachmentRecord] = {}
        self._global_image_cache_lock = threading.Lock()

    def enabled(self) -> bool:
        cfg = self._config_getter()
        return bool(getattr(cfg, "enabled", False))

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
        await asyncio.to_thread(self._cleanup_gif_frame_files, uid)
        return True
