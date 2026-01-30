import asyncio
import importlib.util
import json
import logging
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class SkillStats:
    count: int = 0
    success: int = 0
    failure: int = 0
    total_duration: float = 0.0
    last_duration: float = 0.0
    last_error: Optional[str] = None
    last_called_at: Optional[float] = None

    def record_success(self, duration: float) -> None:
        self.count += 1
        self.success += 1
        self.total_duration += duration
        self.last_duration = duration
        self.last_error = None
        self.last_called_at = time.time()

    def record_failure(self, duration: float, error: str) -> None:
        self.count += 1
        self.failure += 1
        self.total_duration += duration
        self.last_duration = duration
        self.last_error = error
        self.last_called_at = time.time()


@dataclass
class SkillItem:
    name: str
    config: Dict[str, Any]
    handler_path: Optional[Path]
    module_name: Optional[str]
    handler: Optional[Callable[[Dict[str, Any], Dict[str, Any]], Awaitable[Any]]] = None
    loaded: bool = False


class BaseRegistry:
    """
    基础注册表类，用于发现和加载技能（Tools/Agents）。

    提供统一的加载、验证、延迟加载执行、统计和热重载逻辑。
    """

    def __init__(
        self,
        base_dir: Path | str | None = None,
        kind: str = "skill",
        timeout_seconds: float = 120.0,
    ) -> None:
        if base_dir:
            self.base_dir = Path(base_dir)
        else:
            self.base_dir = Path(".")

        self.kind = kind
        self.timeout_seconds = timeout_seconds
        self._items: Dict[str, SkillItem] = {}
        self._items_schema: List[Dict[str, Any]] = []
        self._stats: Dict[str, SkillStats] = {}

        self._items_lock = asyncio.Lock()
        self._reload_lock = asyncio.Lock()

        self._watch_paths: List[Path] = [self.base_dir]
        self._watch_task: Optional[asyncio.Task[None]] = None
        self._watch_stop: Optional[asyncio.Event] = None
        self._last_snapshot: Dict[str, tuple[int, int]] = {}
        self._watch_filenames: set[str] = {"config.json", "handler.py"}

        self.skills_root = self._resolve_skills_root(self.base_dir)

    def _resolve_skills_root(self, base_dir: Path) -> Path:
        if base_dir.name in {"tools", "agents", "toolsets"} and base_dir.parent.name:
            return base_dir.parent
        return base_dir

    def set_watch_paths(self, paths: List[Path]) -> None:
        self._watch_paths = paths

    def set_watch_filenames(self, filenames: set[str]) -> None:
        self._watch_filenames = filenames

    def _log_event(self, event: str, name: str = "", **fields: Any) -> None:
        parts = [f"event={event}", f"kind={self.kind}"]
        if name:
            parts.append(f"name={name}")
        for key, value in fields.items():
            parts.append(f"{key}={value}")
        logger.info("[skills] " + " ".join(parts))

    def _reset_items(self) -> None:
        self._items = {}
        self._items_schema = []

    def load_items(self) -> None:
        """从 base_dir 自动发现并加载项（仅加载 config，不导入 handler）。"""
        self._reset_items()

        if not self.base_dir.exists():
            logger.warning(f"目录不存在: {self.base_dir}")
            return

        self._discover_items_in_dir(self.base_dir, prefix="")

        active_names = set(self._items.keys())
        self._stats = {
            name: self._stats.get(name, SkillStats()) for name in active_names
        }

        item_names = list(self._items.keys())
        logger.info(
            f"[{self.__class__.__name__}] 成功加载了 {len(self._items_schema)} 个项目: {', '.join(item_names)}"
        )

    def _discover_items_in_dir(self, parent_dir: Path, prefix: str) -> None:
        for item in parent_dir.iterdir():
            if item.is_dir() and not item.name.startswith("_"):
                self._register_item_from_dir(item, prefix=prefix)

    def _register_item_from_dir(self, item_dir: Path, prefix: str = "") -> None:
        config_path = item_dir / "config.json"
        handler_path = item_dir / "handler.py"

        if not config_path.exists() or not handler_path.exists():
            logger.debug(f"目录 {item_dir} 缺少 config.json 或 handler.py，跳过")
            return

        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)

            if "name" not in config.get("function", {}):
                logger.error(f"配置无效 {item_dir}: 缺少 function.name")
                return

            original_name = config["function"]["name"]
            full_name = f"{prefix}{original_name}"

            if prefix:
                import copy

                config = copy.deepcopy(config)
                config["function"]["name"] = full_name

            module_name = self._build_module_name(item_dir)

            item = SkillItem(
                name=full_name,
                config=config,
                handler_path=handler_path,
                module_name=module_name,
            )

            self._items[full_name] = item
            self._items_schema.append(config)
            self._stats.setdefault(full_name, SkillStats())

        except Exception as e:
            logger.error(f"从 {item_dir} 加载失败: {e}")

    def _build_module_name(self, item_dir: Path) -> str:
        try:
            relative = item_dir.relative_to(self.skills_root)
            parts = [self.skills_root.name] + list(relative.parts)
            return ".".join(parts)
        except ValueError:
            parts = list(item_dir.parts[-3:])
            return ".".join(parts)

    def _patch_agent_tool_registry(self, module: Any) -> None:
        """为 AgentToolRegistry 注入 MCP 执行逻辑（若存在）。"""
        if not hasattr(module, "AgentToolRegistry"):
            return

        registry_cls = getattr(module, "AgentToolRegistry")
        if getattr(registry_cls, "_mcp_patched", False):
            return

        if not hasattr(registry_cls, "execute_tool"):
            return

        original_execute_tool = registry_cls.execute_tool

        async def execute_tool(
            self: Any,
            tool_name: str,
            args: Dict[str, Any],
            context: Dict[str, Any],
        ) -> str:
            if tool_name in getattr(self, "_tools_handlers", {}):
                if asyncio.iscoroutinefunction(original_execute_tool):
                    result = await original_execute_tool(self, tool_name, args, context)
                    return str(result)
                result = original_execute_tool(self, tool_name, args, context)
                return str(result)

            ai_client = context.get("ai_client")
            agent_name = context.get("agent_name")
            if (
                ai_client
                and agent_name
                and hasattr(ai_client, "get_active_agent_mcp_registry")
            ):
                registry = ai_client.get_active_agent_mcp_registry(agent_name)
                if registry:
                    result = await registry.execute_tool(tool_name, args, context)
                    return str(result)

            if asyncio.iscoroutinefunction(original_execute_tool):
                result = await original_execute_tool(self, tool_name, args, context)
                return str(result)
            result = original_execute_tool(self, tool_name, args, context)
            return str(result)

        registry_cls.execute_tool = execute_tool
        registry_cls._mcp_patched = True

    def _load_handler_for_item(
        self, item: SkillItem, reload_module: bool = False
    ) -> None:
        if item.handler is not None and not reload_module:
            return

        if not item.handler_path or not item.module_name:
            return

        if reload_module and item.module_name in sys.modules:
            del sys.modules[item.module_name]

        spec = importlib.util.spec_from_file_location(
            item.module_name, item.handler_path
        )
        if spec is None or spec.loader is None:
            raise RuntimeError(f"加载处理器 spec 失败: {item.handler_path}")

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self._patch_agent_tool_registry(module)

        if not hasattr(module, "execute"):
            raise RuntimeError(f"{item.handler_path} 的处理器缺少 'execute' 函数")

        item.handler = module.execute
        item.loaded = True

    def register_external_item(
        self,
        name: str,
        schema: Dict[str, Any],
        handler: Callable[[Dict[str, Any], Dict[str, Any]], Awaitable[Any]],
    ) -> None:
        item = SkillItem(
            name=name,
            config=schema,
            handler_path=None,
            module_name=None,
            handler=handler,
            loaded=True,
        )
        self._items[name] = item
        self._items_schema.append(schema)
        self._stats.setdefault(name, SkillStats())

    def get_schema(self) -> List[Dict[str, Any]]:
        return self._items_schema

    def get_stats(self) -> Dict[str, SkillStats]:
        return self._stats

    async def execute(
        self, name: str, args: Dict[str, Any], context: Dict[str, Any]
    ) -> str:
        async with self._items_lock:
            item = self._items.get(name)

        if not item:
            return f"未找到项目: {name}"

        start_time = time.monotonic()
        try:
            if item.handler is None and item.handler_path:
                self._load_handler_for_item(item)
            handler = item.handler
            if not handler:
                return f"未找到项目: {name}"

            result = await self._execute_with_timeout(handler, args, context)
            duration = time.monotonic() - start_time

            self._stats[name].record_success(duration)
            self._log_event(
                "execute", name, status="success", duration_ms=int(duration * 1000)
            )
            return str(result)

        except asyncio.TimeoutError:
            duration = time.monotonic() - start_time
            self._stats[name].record_failure(duration, "timeout")
            self._log_event(
                "execute", name, status="timeout", duration_ms=int(duration * 1000)
            )
            return f"执行 {name} 超时 (>{int(self.timeout_seconds)}s)"

        except asyncio.CancelledError:
            duration = time.monotonic() - start_time
            self._stats[name].record_failure(duration, "cancelled")
            self._log_event(
                "execute", name, status="cancelled", duration_ms=int(duration * 1000)
            )
            return f"执行 {name} 已取消"

        except Exception as e:
            duration = time.monotonic() - start_time
            self._stats[name].record_failure(duration, str(e))
            logger.exception(f"[执行异常] {name}")
            self._log_event(
                "execute", name, status="error", duration_ms=int(duration * 1000)
            )
            return f"执行 {name} 时出错: {str(e)}"

    async def _execute_with_timeout(
        self,
        handler: Callable[[Dict[str, Any], Dict[str, Any]], Awaitable[Any]],
        args: Dict[str, Any],
        context: Dict[str, Any],
    ) -> Any:
        if asyncio.iscoroutinefunction(handler):
            return await asyncio.wait_for(
                handler(args, context), timeout=self.timeout_seconds
            )
        return await asyncio.wait_for(
            asyncio.to_thread(handler, args, context), timeout=self.timeout_seconds
        )

    def _compute_snapshot(self) -> Dict[str, tuple[int, int]]:
        snapshot: Dict[str, tuple[int, int]] = {}
        target_names = self._watch_filenames
        for root in self._watch_paths:
            if not root.exists():
                continue
            for path in root.rglob("*"):
                if path.is_file() and path.name in target_names:
                    try:
                        stat = path.stat()
                        snapshot[str(path)] = (int(stat.st_mtime_ns), int(stat.st_size))
                    except OSError:
                        continue
        return snapshot

    async def _reload_items(self) -> None:
        async with self._items_lock:
            self.load_items()

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
                    await self._reload_items()
                self._log_event("reload", count=len(self._items))

    def start_hot_reload(self, interval: float = 2.0, debounce: float = 0.5) -> None:
        if self._watch_task:
            return
        self._watch_stop = asyncio.Event()
        self._watch_task = asyncio.create_task(self._watch_loop(interval, debounce))
        self._log_event("watch_start", interval_s=interval, debounce_s=debounce)

    async def stop_hot_reload(self) -> None:
        if not self._watch_task or not self._watch_stop:
            return
        self._watch_stop.set()
        try:
            await self._watch_task
        finally:
            self._watch_task = None
            self._watch_stop = None
            self._log_event("watch_stop")
