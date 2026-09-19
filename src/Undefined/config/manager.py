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

    def replace(self, config: Config) -> None:
        """替换缓存的配置实例（库嵌入 ``set_config`` 注入时使用）。"""
        self._config = config

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

    async def stop_hot_reload(self, timeout: float | None = 2.0) -> None:
        if not self._watch_task or not self._watch_stop:
            return
        self._watch_stop.set()
        task = self._watch_task
        try:
            if timeout is None:
                await task
            else:
                try:
                    await asyncio.wait_for(task, timeout=timeout)
                except asyncio.TimeoutError:
                    logger.warning("[配置] 热重载停止超时，正在取消任务")
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
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
        """把热更新变更分发给订阅者。

        单个回调失败不再静默丢弃：记录 error 级日志与失败回调名单，其余回调继续
        执行。调用方据此可以在日志中看到“配置已改、行为未改”的不一致。
        """
        if not self._callbacks:
            return
        config = self._config
        if config is None:
            return
        failed: list[str] = []
        for callback in list(self._callbacks):
            try:
                callback(config, changes)
            except Exception:
                name = getattr(callback, "__qualname__", repr(callback))
                failed.append(name)
                logger.error("[配置] 热更新回调执行失败: %s", name, exc_info=True)
        if failed:
            logger.error(
                "[配置] 以下回调未完成，相关运行时配置可能未生效，请修复后重新保存配置或重启: %s",
                ", ".join(failed),
            )
