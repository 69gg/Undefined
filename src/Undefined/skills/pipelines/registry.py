"""自动处理管线注册器。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import importlib.util
import json
import logging
from pathlib import Path
import sys
import time
from types import ModuleType
from typing import Any, Awaitable, Callable

from Undefined.skills.pipelines.models import (
    PipelineContext,
    PipelineDetection,
)

logger = logging.getLogger(__name__)

DetectHandler = Callable[[PipelineContext], Awaitable[PipelineDetection | None]]
ProcessHandler = Callable[[PipelineDetection, PipelineContext], Awaitable[None]]


@dataclass(frozen=True)
class PipelineItem:
    name: str
    description: str
    order: int
    handler_path: Path
    module_name: str
    detect: DetectHandler
    process: ProcessHandler


class PipelineRegistry:
    """发现、热重载并并行运行自动处理管线。"""

    def __init__(self, base_dir: Path | str | None = None) -> None:
        self.base_dir = (
            Path(base_dir) if base_dir is not None else Path(__file__).parent
        )
        self._items: dict[str, PipelineItem] = {}
        self._items_lock = asyncio.Lock()
        self._reload_lock = asyncio.Lock()
        self._watch_task: asyncio.Task[None] | None = None
        self._watch_stop: asyncio.Event | None = None
        self._last_snapshot: dict[str, tuple[int, int]] = {}
        self._watch_filenames: set[str] = {"config.json", "handler.py"}

    def load_items(self) -> None:
        self._items = self._load_items_sync()

    async def load_items_async(self) -> None:
        async with self._reload_lock:
            await self._reload_items()

    def _load_items_sync(self) -> dict[str, PipelineItem]:
        items: dict[str, PipelineItem] = {}
        if not self.base_dir.exists():
            logger.warning("[pipelines] 目录不存在: %s", self.base_dir)
            return items

        for item_dir in sorted(self.base_dir.iterdir()):
            if not item_dir.is_dir() or item_dir.name.startswith("_"):
                continue
            item = self._load_item(item_dir)
            if item is not None:
                items[item.name] = item

        loaded_items = dict(sorted(items.items(), key=lambda pair: pair[1].order))
        logger.info(
            "[pipelines] 已加载自动处理管线: count=%s names=%s",
            len(loaded_items),
            ",".join(loaded_items),
        )
        return loaded_items

    def _load_item(self, item_dir: Path) -> PipelineItem | None:
        config_path = item_dir / "config.json"
        handler_path = item_dir / "handler.py"
        if not config_path.exists() or not handler_path.exists():
            logger.debug("[pipelines] 跳过缺少 config/handler 的目录: %s", item_dir)
            return None

        try:
            config = self._load_config(config_path)
            if not config.get("enabled", True):
                return None
            name = str(config["name"]).strip()
            description = str(config.get("description", "")).strip()
            order = int(config.get("order", 100))
            module = self._load_handler_module(name, handler_path)
            detect = getattr(module, "detect", None)
            process = getattr(module, "process", None)
            if not callable(detect) or not callable(process):
                raise RuntimeError(
                    "handler.py 必须提供 detect(context) 和 process(detection, context)"
                )
            return PipelineItem(
                name=name,
                description=description,
                order=order,
                handler_path=handler_path,
                module_name=self._build_module_name(name),
                detect=detect,
                process=process,
            )
        except Exception:
            logger.exception("[pipelines] 加载管线失败: %s", item_dir)
            return None

    def _load_config(self, config_path: Path) -> dict[str, Any]:
        with open(config_path, "r", encoding="utf-8") as file:
            data = json.load(file)
        if not isinstance(data, dict) or not str(data.get("name", "")).strip():
            raise ValueError("config.json 必须包含 name")
        return data

    def _build_module_name(self, name: str) -> str:
        return f"Undefined.skills.pipelines.{name}.handler"

    def _load_handler_module(self, name: str, handler_path: Path) -> ModuleType:
        module_name = self._build_module_name(name)
        if module_name in sys.modules:
            del sys.modules[module_name]

        spec = importlib.util.spec_from_file_location(module_name, handler_path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"无法加载 handler: {handler_path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        try:
            spec.loader.exec_module(module)
        except Exception:
            if sys.modules.get(module_name) is module:
                del sys.modules[module_name]
            raise
        return module

    async def run(self, context: PipelineContext) -> list[PipelineDetection]:
        detections = await self.detect(context)
        if detections:
            await self.process(detections, context)
        return detections

    async def detect(self, context: PipelineContext) -> list[PipelineDetection]:
        async with self._items_lock:
            items = list(self._items.values())
        if not items:
            return []

        results = await asyncio.gather(
            *(self._detect_one(item, context) for item in items),
            return_exceptions=True,
        )
        detections: list[PipelineDetection] = []
        for item, result in zip(items, results, strict=True):
            if isinstance(result, BaseException):
                logger.exception(
                    "[pipelines] 检测失败: name=%s",
                    item.name,
                    exc_info=(type(result), result, result.__traceback__),
                )
                continue
            if result is not None:
                detections.append(result)
        return detections

    async def _detect_one(
        self, item: PipelineItem, context: PipelineContext
    ) -> PipelineDetection | None:
        start = time.monotonic()
        detection = await item.detect(context)
        duration_ms = int((time.monotonic() - start) * 1000)
        if detection is not None:
            logger.info(
                "[pipelines] 命中管线: name=%s items=%s duration_ms=%s",
                item.name,
                len(detection.items),
                duration_ms,
            )
        return detection

    async def process(
        self,
        detections: list[PipelineDetection],
        context: PipelineContext,
    ) -> None:
        async with self._items_lock:
            items = dict(self._items)
        tasks: list[Awaitable[None]] = []
        names: list[str] = []
        for detection in detections:
            item = items.get(detection.name)
            if item is None:
                logger.warning(
                    "[pipelines] 命中结果缺少处理器: name=%s", detection.name
                )
                continue
            names.append(detection.name)
            tasks.append(self._process_one(item, detection, context))
        if not tasks:
            return

        results = await asyncio.gather(*tasks, return_exceptions=True)
        for name, result in zip(names, results, strict=True):
            if isinstance(result, BaseException):
                logger.exception(
                    "[pipelines] 处理失败: name=%s",
                    name,
                    exc_info=(type(result), result, result.__traceback__),
                )

    async def _process_one(
        self,
        item: PipelineItem,
        detection: PipelineDetection,
        context: PipelineContext,
    ) -> None:
        start = time.monotonic()
        await item.process(detection, context)
        logger.info(
            "[pipelines] 管线处理完成: name=%s duration_ms=%s",
            item.name,
            int((time.monotonic() - start) * 1000),
        )

    def _compute_snapshot(self) -> dict[str, tuple[int, int]]:
        snapshot: dict[str, tuple[int, int]] = {}
        if not self.base_dir.exists():
            return snapshot
        for path in self.base_dir.rglob("*"):
            if not path.is_file() or path.name not in self._watch_filenames:
                continue
            try:
                stat = path.stat()
                snapshot[str(path)] = (int(stat.st_mtime_ns), int(stat.st_size))
            except OSError:
                continue
        return snapshot

    async def _reload_items(self) -> None:
        items = await asyncio.to_thread(self._load_items_sync)
        async with self._items_lock:
            self._items = items

    async def _watch_loop(self, interval: float, debounce: float) -> None:
        self._last_snapshot = await asyncio.to_thread(self._compute_snapshot)
        last_change = 0.0
        pending = False
        while self._watch_stop and not self._watch_stop.is_set():
            await asyncio.sleep(interval)
            snapshot = await asyncio.to_thread(self._compute_snapshot)
            if snapshot != self._last_snapshot:
                self._last_snapshot = snapshot
                last_change = time.monotonic()
                pending = True
            if pending and (time.monotonic() - last_change) >= debounce:
                pending = False
                async with self._reload_lock:
                    await self._reload_items()
                logger.info("[pipelines] 热重载完成: count=%s", len(self._items))

    def start_hot_reload(self, interval: float = 2.0, debounce: float = 0.5) -> None:
        if self._watch_task is not None:
            return
        self._watch_stop = asyncio.Event()
        self._watch_task = asyncio.create_task(self._watch_loop(interval, debounce))
        logger.info(
            "[pipelines] 热重载已启动: interval=%.2fs debounce=%.2fs",
            interval,
            debounce,
        )

    async def stop_hot_reload(self) -> None:
        if self._watch_task is None or self._watch_stop is None:
            return
        self._watch_stop.set()
        try:
            await self._watch_task
        finally:
            self._watch_task = None
            self._watch_stop = None
            logger.info("[pipelines] 热重载已停止")
