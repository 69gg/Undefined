"""HTML 渲染结果缓存：基于 HTML 内容 hash 缓存渲染图片，避免重复渲染。

关键约束（CLAUDE.md）：磁盘读写必须走 :mod:`Undefined.utils.io`
（``asyncio.to_thread`` + 跨平台文件锁 + 原子写入），禁止在事件循环中直接阻塞 IO。
本模块所有 ``stat`` / ``unlink`` / ``copy`` 都通过 ``asyncio.to_thread`` 包装；
JSON 元数据通过 :func:`Undefined.utils.io.read_json` / :func:`Undefined.utils.io.write_json`
读写，自带文件锁与原子替换。
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict

from Undefined.config import RenderCacheConfig
from Undefined.utils import io as async_io
from Undefined.utils.paths import ensure_dir

logger = logging.getLogger(__name__)

__all__ = [
    "HtmlRenderCache",
    "compute_render_cache_key",
    "get_render_cache",
    "close_render_cache",
    "reset_render_cache",
]


class _CacheEntry(TypedDict):
    path: str
    size_bytes: int
    created_at: float
    last_accessed_at: float


@dataclass(frozen=True)
class _ResolvedConfig:
    """运行时生效的缓存策略快照。"""

    enabled: bool
    max_entries: int
    max_size_bytes: int
    flush_interval_seconds: float


class HtmlRenderCache:
    """HTML 渲染结果 LRU 缓存。

    使用前必须先 ``await cache.initialize()``；推荐通过 :func:`get_render_cache`
    获取全局单例，单例工厂会负责 lazy initialize。

    禁用（``config.enabled=False``）时所有 ``get`` / ``put`` 都是 no-op，
    缓存目录不会被读写。
    """

    _entries: dict[str, _CacheEntry]
    _lock: asyncio.Lock
    _dirty: bool
    _last_flush: float
    _cache_file: Path
    _image_dir: Path
    _config: _ResolvedConfig
    _initialized: bool

    def __init__(
        self,
        cache_file: Path,
        *,
        max_entries: int = 50,
        max_size_mb: int = 50,
        flush_interval_seconds: float = 2.0,
        enabled: bool = True,
    ) -> None:
        ensure_dir(cache_file.parent)
        self._cache_file = cache_file
        self._image_dir = ensure_dir(cache_file.parent / "html")
        self._config = _ResolvedConfig(
            enabled=enabled,
            max_entries=max(1, max_entries),
            max_size_bytes=max(1, max_size_mb) * 1024 * 1024,
            flush_interval_seconds=max(0.0, flush_interval_seconds),
        )
        self._entries = {}
        self._dirty = False
        self._last_flush = 0.0
        self._lock = asyncio.Lock()
        self._initialized = False

    # ---------------------------------------------------------------- factory

    @classmethod
    async def create(
        cls,
        cache_file: Path,
        *,
        max_entries: int = 50,
        max_size_mb: int = 50,
        flush_interval_seconds: float = 2.0,
        enabled: bool = True,
    ) -> HtmlRenderCache:
        """异步工厂：构造并完成 lazy load。"""
        cache = cls(
            cache_file,
            max_entries=max_entries,
            max_size_mb=max_size_mb,
            flush_interval_seconds=flush_interval_seconds,
            enabled=enabled,
        )
        await cache.initialize()
        return cache

    async def initialize(self) -> None:
        """异步加载磁盘元数据；多次调用幂等。"""
        if self._initialized:
            return
        async with self._lock:
            if self._initialized:
                return
            await self._load_locked()
            self._initialized = True

    # ---------------------------------------------------------------- private

    async def _load_locked(self) -> None:
        """读元数据并清理可能残留的 .tmp 文件。完全异步。"""
        # 残留 tmp 清理
        legacy_tmp = self._cache_file.with_suffix(".tmp")
        await async_io.delete_file(legacy_tmp)

        try:
            raw = await async_io.read_json(self._cache_file)
        except Exception:
            logger.warning("[渲染缓存] 加载缓存文件失败，将使用空缓存", exc_info=True)
            self._entries = {}
            return

        if not isinstance(raw, dict):
            self._entries = {}
            return

        loaded: dict[str, _CacheEntry] = {}
        for key, value in raw.items():
            if not isinstance(value, dict):
                continue
            try:
                entry = _CacheEntry(
                    path=str(value["path"]),
                    size_bytes=int(value.get("size_bytes", 0)),
                    created_at=float(value.get("created_at", 0.0)),
                    last_accessed_at=float(value.get("last_accessed_at", 0.0)),
                )
            except (KeyError, TypeError, ValueError):
                continue
            loaded[str(key)] = entry

        owned: dict[str, _CacheEntry] = {}
        for key, entry in loaded.items():
            if self._is_cache_owned_path(Path(entry["path"])):
                owned[key] = entry
        if len(owned) != len(loaded):
            self._dirty = True
        self._entries = owned
        logger.info("[渲染缓存] 已加载 %d 条缓存记录", len(self._entries))

    async def _flush_locked(self, *, force: bool = False) -> None:
        """异步落盘元数据。

        ``force=False`` 时遵循 ``flush_interval_seconds`` 节流，避免热点写盘；
        ``force=True`` 用于关停 / 用户主动触发。
        """
        if not self._dirty:
            return
        now = time.monotonic()
        if (
            not force
            and self._config.flush_interval_seconds > 0
            and now - self._last_flush < self._config.flush_interval_seconds
        ):
            return
        snapshot = dict(self._entries)
        try:
            await async_io.write_json(self._cache_file, snapshot)
            self._dirty = False
            self._last_flush = now
        except Exception:
            logger.warning("[渲染缓存] 保存缓存文件失败", exc_info=True)

    async def _evict_lru_locked(self) -> None:
        cfg = self._config
        # 条目数上限
        while len(self._entries) > cfg.max_entries:
            lru_key = min(
                self._entries,
                key=lambda k: self._entries[k]["last_accessed_at"],
            )
            entry = self._entries.pop(lru_key)
            self._dirty = True
            await async_io.delete_file(Path(entry["path"]))

        # 总字节上限
        total = sum(e["size_bytes"] for e in self._entries.values())
        while total > cfg.max_size_bytes and self._entries:
            lru_key = min(
                self._entries,
                key=lambda k: self._entries[k]["last_accessed_at"],
            )
            entry = self._entries.pop(lru_key)
            total -= entry["size_bytes"]
            self._dirty = True
            await async_io.delete_file(Path(entry["path"]))

    def _cache_path_for_key(self, key: str) -> Path:
        safe_key = "".join(ch for ch in key if ch.isalnum() or ch in {"-", "_"})
        return self._image_dir / f"{safe_key}.png"

    def _is_cache_owned_path(self, path: Path) -> bool:
        try:
            path.resolve().relative_to(self._image_dir.resolve())
            return True
        except ValueError:
            return False

    async def _path_exists(self, path: Path) -> bool:
        return await asyncio.to_thread(path.exists)

    async def _stat_size(self, path: Path) -> int:
        def _stat() -> int:
            try:
                return path.stat().st_size
            except OSError:
                return 0

        return await asyncio.to_thread(_stat)

    async def _copy_into_cache(self, source: Path, dest: Path) -> bool:
        def _copy() -> bool:
            try:
                shutil.copy2(source, dest)
                return True
            except OSError:
                return False

        return await asyncio.to_thread(_copy)

    # ----------------------------------------------------------------- public

    @property
    def enabled(self) -> bool:
        return self._config.enabled

    async def get(self, key: str) -> Path | None:
        if not self._config.enabled:
            return None
        await self.initialize()
        async with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            path = Path(entry["path"])
            if not self._is_cache_owned_path(path) or not await self._path_exists(path):
                del self._entries[key]
                self._dirty = True
                return None
            entry["last_accessed_at"] = time.time()
            await self._flush_locked()
            return path

    async def put(self, key: str, image_path: str | Path, size_bytes: int) -> None:
        if not self._config.enabled:
            return
        await self.initialize()
        source_path = Path(image_path)
        if not await self._path_exists(source_path):
            return
        async with self._lock:
            cache_path = self._cache_path_for_key(key)
            existing = self._entries.get(key)
            if existing is not None:
                existing_path = Path(existing["path"])
                if self._is_cache_owned_path(existing_path) and await self._path_exists(
                    existing_path
                ):
                    existing["last_accessed_at"] = time.time()
                    self._dirty = True
                    await self._flush_locked()
                    return

            if source_path.resolve() != cache_path.resolve():
                if not await self._copy_into_cache(source_path, cache_path):
                    return
            actual_size = await self._stat_size(cache_path)
            self._entries[key] = _CacheEntry(
                path=str(cache_path),
                size_bytes=actual_size if actual_size > 0 else size_bytes,
                created_at=time.time(),
                last_accessed_at=time.time(),
            )
            self._dirty = True
            await self._evict_lru_locked()
            await self._flush_locked()

    async def copy_to(self, key: str, dest: str | Path) -> bool:
        """命中缓存时把图片拷贝到 ``dest``，不命中返回 False。

        集中所有"读后拷贝"路径，避免调用方再写一份同步 IO。
        """
        cached_path = await self.get(key)
        if cached_path is None:
            return False
        return await self._copy_into_cache(cached_path, Path(dest))

    async def close(self) -> None:
        """强制刷盘元数据；用于程序关停。"""
        async with self._lock:
            await self._flush_locked(force=True)


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


def _resolve_render_cache_config() -> RenderCacheConfig:
    """从全局配置读取 RenderCacheConfig，失败时回落默认值。"""
    try:
        from Undefined.config import get_config

        runtime_config = get_config(strict=False)
    except Exception:
        logger.debug("[渲染缓存] 读取配置失败，回退到默认参数", exc_info=True)
        return RenderCacheConfig()
    cache_cfg = getattr(runtime_config, "render_cache", None)
    if isinstance(cache_cfg, RenderCacheConfig):
        return cache_cfg
    return RenderCacheConfig()


async def get_render_cache() -> HtmlRenderCache:
    """获取全局渲染缓存单例（lazy load）。

    单例的 enabled / 容量由 ``[render.cache]`` 决定；
    禁用时仍返回单例对象，但所有 get/put 立即短路。
    """
    # global
    global _cache
    if _cache is not None:
        await _cache.initialize()
        return _cache
    async with _cache_lock:
        if _cache is not None:
            await _cache.initialize()
            return _cache
        from Undefined.utils.paths import RENDER_CACHE_DIR

        cfg = _resolve_render_cache_config()
        cache = HtmlRenderCache(
            ensure_dir(RENDER_CACHE_DIR) / "_html_render_cache.json",
            max_entries=cfg.max_entries,
            max_size_mb=cfg.max_size_mb,
            flush_interval_seconds=cfg.flush_interval_seconds,
            enabled=cfg.enabled,
        )
        await cache.initialize()
        _cache = cache
        return cache


async def close_render_cache() -> None:
    """关停时调用：刷盘并丢弃单例。"""
    # global
    global _cache
    cache = _cache
    if cache is None:
        return
    try:
        await cache.close()
    finally:
        _cache = None


def reset_render_cache() -> None:
    """仅供测试使用：丢弃单例（不刷盘），下次调用重新加载。"""
    # global
    global _cache
    _cache = None
