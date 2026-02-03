"""配置管理与热重载"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any, Callable

from .loader import CONFIG_PATH, LOCAL_CONFIG_PATH, Config

logger = logging.getLogger(__name__)

ConfigChangeCallback = Callable[[Config, dict[str, tuple[Any, Any]]], None]


class ConfigManager:
    def __init__(self, config_path: Path | None = None) -> None:
        self.config_path = config_path or CONFIG_PATH
        self._config: Config | None = None
        self._callbacks: list[ConfigChangeCallback] = []
        self._watch_task: asyncio.Task[None] | None = None
        self._watch_stop: asyncio.Event | None = None
        self._last_snapshot: dict[str, tuple[int, int]] = {}
        self._reload_lock = asyncio.Lock()

    def load(self, strict: bool = True) -> Config:
        if self._config is None:
            self._config = Config.load(config_path=self.config_path, strict=strict)
        return self._config

    def reload(self, strict: bool = False) -> dict[str, tuple[Any, Any]]:
        if self._config is None:
            self._config = Config.load(config_path=self.config_path, strict=strict)
            return {}
        new_config = Config.load(config_path=self.config_path, strict=strict)
        changes = self._config.update_from(new_config)
        if changes:
            self._notify(changes)
        return changes

    def subscribe(self, callback: ConfigChangeCallback) -> None:
        self._callbacks.append(callback)

    def start_hot_reload(self, interval: float = 2.0, debounce: float = 0.5) -> None:
        if self._watch_task:
            return
        self._watch_stop = asyncio.Event()
        self._watch_task = asyncio.create_task(self._watch_loop(interval, debounce))
        logger.info(
            "[配置] 热重载已启动: interval=%.2fs debounce=%.2fs", interval, debounce
        )

    async def stop_hot_reload(self) -> None:
        if not self._watch_task or not self._watch_stop:
            return
        self._watch_stop.set()
        try:
            await self._watch_task
        finally:
            self._watch_task = None
            self._watch_stop = None
            logger.info("[配置] 热重载已停止")

    async def _watch_loop(self, interval: float, debounce: float) -> None:
        self._last_snapshot = self._compute_snapshot()
        last_change = 0.0
        pending = False
        while self._watch_stop and not self._watch_stop.is_set():
            await asyncio.sleep(interval)
            snapshot = self._compute_snapshot()
            if snapshot != self._last_snapshot:
                self._last_snapshot = snapshot
                last_change = time.monotonic()
                pending = True
            if pending and (time.monotonic() - last_change) >= debounce:
                pending = False
                async with self._reload_lock:
                    try:
                        changes = self.reload(strict=False)
                        if changes:
                            logger.info("[配置] 已应用热更新: %s", ", ".join(changes))
                    except Exception as exc:
                        logger.warning("[配置] 热重载失败: %s", exc)

    def _compute_snapshot(self) -> dict[str, tuple[int, int]]:
        snapshot: dict[str, tuple[int, int]] = {}
        for path in (self.config_path, LOCAL_CONFIG_PATH):
            if not path.exists():
                continue
            try:
                stat = path.stat()
                snapshot[str(path)] = (int(stat.st_mtime_ns), int(stat.st_size))
            except OSError:
                continue
        return snapshot

    def _notify(self, changes: dict[str, tuple[Any, Any]]) -> None:
        if not self._callbacks:
            return
        for callback in list(self._callbacks):
            try:
                callback(self._config, changes)  # type: ignore[arg-type]
            except Exception:
                logger.debug("配置回调执行失败", exc_info=True)
