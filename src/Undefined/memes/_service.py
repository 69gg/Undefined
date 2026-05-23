"""MemeService 门面类。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
import logging
import math
import mimetypes
from pathlib import Path
import re
import threading
from typing import Any

from openai import APIConnectionError, APIStatusError, APITimeoutError
from PIL import Image

from Undefined.attachments import AttachmentRecord
from Undefined.memes.models import (
    build_search_text,
    normalize_string_list,
)
from Undefined.memes.store import MemeStore
from Undefined.memes.vector_store import MemeVectorStore
from Undefined.utils.paths import ensure_dir
from Undefined.memes.ingest import MemeIngestMixin
from Undefined.memes.search import MemeSearchMixin

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


def _is_retryable_llm_error(exc: Exception) -> bool:
    """判断 LLM 调用异常是否应触发 worker 级重试。"""
    if isinstance(exc, (APIConnectionError, APITimeoutError)):
        return True
    if isinstance(exc, APIStatusError):
        return exc.status_code == 429 or exc.status_code >= 500
    return False


def _extract_gif_frames(source_path: Path, n_frames: int) -> list[Image.Image]:
    """从 GIF 中均匀采样 *n_frames* 帧（含首末帧），返回 RGBA Image 列表。"""
    with Image.open(source_path) as image:
        total = getattr(image, "n_frames", 1)
        if total <= 1:
            image.seek(0)
            return [image.convert("RGBA").copy()]
        n = min(n_frames, total)
        if n <= 1:
            image.seek(0)
            return [image.convert("RGBA").copy()]
        indices = _sample_frame_indices(total, n)
        frames: list[Image.Image] = []
        for idx in indices:
            image.seek(idx)
            frames.append(image.convert("RGBA").copy())
        return frames


def _sample_frame_indices(total: int, n: int) -> list[int]:
    """生成均匀采样的帧索引列表（始终包含首帧和末帧）。"""
    if n >= total:
        return list(range(total))
    if n == 1:
        return [0]
    if n == 2:
        return [0, total - 1]
    indices = [round(i * (total - 1) / (n - 1)) for i in range(n)]
    # 去重并保持顺序
    seen: set[int] = set()
    result: list[int] = []
    for idx in indices:
        if idx not in seen:
            seen.add(idx)
            result.append(idx)
    return result


def _compose_grid(frames: list[Image.Image], output_path: Path) -> None:
    """将多帧拼接为网格图并保存为 PNG。"""
    n = len(frames)
    if n == 0:
        return
    if n == 1:
        frames[0].save(output_path, format="PNG")
        return
    cols = math.ceil(math.sqrt(n))
    rows = math.ceil(n / cols)
    fw, fh = frames[0].size
    grid = Image.new("RGBA", (cols * fw, rows * fh), (0, 0, 0, 0))
    for i, frame in enumerate(frames):
        resized = (
            frame.resize((fw, fh), Image.Resampling.LANCZOS)
            if frame.size != (fw, fh)
            else frame
        )
        x = (i % cols) * fw
        y = (i // cols) * fh
        grid.paste(resized, (x, y))
    grid.save(output_path, format="PNG")


@dataclass
class _IngestDigestLockEntry:
    lock: asyncio.Lock
    users: int = 0


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
        self._ingest_digest_locks: dict[str, _IngestDigestLockEntry] = {}
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
