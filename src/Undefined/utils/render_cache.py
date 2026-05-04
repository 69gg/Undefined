"""HTML 渲染结果缓存：基于 HTML 内容 hash 缓存渲染图片，避免重复渲染。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import time
from pathlib import Path
from typing import TypedDict

from Undefined.utils.paths import ensure_dir

logger = logging.getLogger(__name__)

__all__ = [
    "HtmlRenderCache",
    "compute_render_cache_key",
    "get_render_cache",
]

_DEFAULT_MAX_ENTRIES = 50
_DEFAULT_MAX_SIZE_MB = 50
_MIN_FLUSH_INTERVAL = 2.0


class _CacheEntry(TypedDict):
    path: str
    size_bytes: int
    created_at: float
    last_accessed_at: float


class HtmlRenderCache:
    _entries: dict[str, _CacheEntry]
    _lock: asyncio.Lock
    _dirty: bool
    _last_flush: float
    _cache_file: Path
    _max_entries: int
    _max_size_bytes: int

    def __init__(
        self,
        cache_file: Path,
        *,
        max_entries: int = _DEFAULT_MAX_ENTRIES,
        max_size_mb: int = _DEFAULT_MAX_SIZE_MB,
    ) -> None:
        ensure_dir(cache_file.parent)
        self._cache_file = cache_file
        self._max_entries = max_entries
        self._max_size_bytes = max(1, max_size_mb) * 1024 * 1024
        self._entries = {}
        self._dirty = False
        self._last_flush = 0.0
        self._lock = asyncio.Lock()
        self._load()

    def _load(self) -> None:
        # 清理上次可能残留的 .tmp 文件
        tmp_file = self._cache_file.with_suffix(".tmp")
        if tmp_file.exists():
            try:
                tmp_file.unlink()
            except OSError:
                pass
        try:
            if self._cache_file.exists():
                raw = json.loads(self._cache_file.read_text(encoding="utf-8"))
                self._entries = {k: _CacheEntry(**v) for k, v in raw.items()}  # type: ignore
                logger.info("[渲染缓存] 已加载 %d 条缓存记录", len(self._entries))
        except Exception:
            logger.warning("[渲染缓存] 加载缓存文件失败，将使用空缓存", exc_info=True)
            self._entries = {}

    async def _save_locked(self) -> None:
        if not self._dirty:
            return
        now = time.monotonic()
        if now - self._last_flush < _MIN_FLUSH_INTERVAL:
            return
        try:
            tmp = self._cache_file.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(self._entries, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            os.replace(tmp, self._cache_file)
            self._dirty = False
            self._last_flush = now
        except Exception:
            logger.warning("[渲染缓存] 保存缓存文件失败", exc_info=True)

    async def _evict_lru_locked(self) -> None:
        while len(self._entries) > self._max_entries:
            lru_key = min(
                self._entries,
                key=lambda k: self._entries[k]["last_accessed_at"],
            )
            entry = self._entries.pop(lru_key)
            self._dirty = True
            try:
                Path(entry["path"]).unlink(missing_ok=True)
            except OSError:
                pass

        total = sum(e["size_bytes"] for e in self._entries.values())
        while total > self._max_size_bytes and self._entries:
            lru_key = min(
                self._entries,
                key=lambda k: self._entries[k]["last_accessed_at"],
            )
            entry = self._entries.pop(lru_key)
            total -= entry["size_bytes"]
            self._dirty = True
            try:
                Path(entry["path"]).unlink(missing_ok=True)
            except OSError:
                pass

    async def get(self, key: str) -> Path | None:
        async with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            path = Path(entry["path"])
            if not path.exists():
                del self._entries[key]
                self._dirty = True
                return None
            entry["last_accessed_at"] = time.time()
            return path

    async def put(self, key: str, image_path: str | Path, size_bytes: int) -> None:
        path = Path(image_path)
        async with self._lock:
            if key in self._entries:
                existing_path = Path(self._entries[key]["path"])
                if existing_path.exists():
                    self._entries[key]["last_accessed_at"] = time.time()
                    return

            self._entries[key] = _CacheEntry(
                path=str(path),
                size_bytes=size_bytes,
                created_at=time.time(),
                last_accessed_at=time.time(),
            )
            self._dirty = True
            await self._evict_lru_locked()
            await self._save_locked()


_cache: HtmlRenderCache | None = None
_cache_lock: asyncio.Lock = asyncio.Lock()


def compute_render_cache_key(
    html_content: str,
    viewport_width: int,
    screenshot_selector: str | None,
    proxy: str | None,
) -> str:
    data = (
        html_content
        + f"|{viewport_width}"
        + f"|{str(screenshot_selector) if screenshot_selector is not None else ''}"
        + f"|{str(proxy) if proxy is not None else ''}"
    )
    return hashlib.sha256(data.encode()).hexdigest()


async def get_render_cache() -> HtmlRenderCache:
    global _cache
    if _cache is not None:
        return _cache
    async with _cache_lock:
        if _cache is not None:
            return _cache
        from Undefined.utils.paths import RENDER_CACHE_DIR

        _cache = HtmlRenderCache(
            ensure_dir(RENDER_CACHE_DIR) / "_html_render_cache.json",
            max_entries=_DEFAULT_MAX_ENTRIES,
            max_size_mb=_DEFAULT_MAX_SIZE_MB,
        )
        return _cache
