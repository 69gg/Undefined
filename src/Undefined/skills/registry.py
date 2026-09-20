import asyncio
import importlib.util
import json
import logging
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional

from Undefined.utils.logging import format_log_payload, log_debug_json
from Undefined.utils.tool_calls import parse_tool_arguments

logger = logging.getLogger(__name__)

# handler 模块名的前缀必须是真实可导入的包路径，否则 handler.py 内的
# 相对导入（如 `from .docker_utils import ...`）会因为顶层包不存在而失败。
_PACKAGE_PREFIX: str = __package__ or "Undefined.skills"
_REAL_PACKAGE_ROOT: Path = Path(__file__).resolve().parent
_SYNTHETIC_PREFIX = "_undefined_skill_modules"


def _is_under_real_package(path: Path) -> bool:
    """判断目录是否属于随包发布的 skills 目录。"""
    try:
        path.resolve().relative_to(_REAL_PACKAGE_ROOT)
    except (OSError, ValueError):
        return False
    return True


class RegistryExecutionTimeoutError(asyncio.TimeoutError):
    """由注册表超时包装器抛出的超时异常。"""


@dataclass
class SkillStats:
    """技能执行统计数据类

    记录单个技能（工具或智能体）的执行次数、成功率、耗时及最后一次错误信息。
    """

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
    """技能项元数据

    封装了技能的配置信息、处理函数以及加载状态。
    """

    name: str
    config: Dict[str, Any]
    handler_path: Optional[Path]
    module_name: Optional[str]
    handler: Optional[Callable[[Dict[str, Any], Dict[str, Any]], Awaitable[Any]]] = None
    loaded: bool = False
    # handler 导入失败的原因；不为空表示该项不可执行，也不会进入对外 schema
    load_error: Optional[str] = None


class BaseRegistry:
    """
    基础注册表类，用于发现和加载技能（Tools/Agents）。

    提供统一的加载、验证、延迟加载执行、统计和热重载逻辑。
    """

    def __init__(
        self,
        base_dir: Path | str | None = None,
        kind: str = "skill",
        timeout_seconds: float = 480.0,
    ) -> None:
        if base_dir:
            self.base_dir = Path(base_dir)
        else:
            self.base_dir = Path(".")

        self.kind = kind
        self.timeout_seconds = timeout_seconds
        self._items: Dict[str, SkillItem] = {}
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
        """解析技能定义的根目录，用于计算模块导入路径"""
        if base_dir.name in {"tools", "agents", "toolsets"} and base_dir.parent.name:
            return base_dir.parent
        return base_dir

    def set_watch_paths(self, paths: List[Path]) -> None:
        self._watch_paths = paths

    def set_watch_filenames(self, filenames: set[str]) -> None:
        self._watch_filenames = filenames

    def _has_timeout(self) -> bool:
        return self.timeout_seconds > 0

    def _log_event(self, event: str, name: str = "", **fields: Any) -> None:
        parts = [f"event={event}", f"kind={self.kind}"]
        if name:
            parts.append(f"name={name}")
        for key, value in fields.items():
            parts.append(f"{key}={value}")
        logger.info("[skills] " + " ".join(parts))

    def _reset_items(self) -> None:
        self._items = {}

    def load_items(self) -> None:
        """从 base_dir 自动发现技能定义，并导入 handler 暴露加载失败。"""
        self._reset_items()

        if not self.base_dir.exists():
            logger.warning(f"目录不存在: {self.base_dir}")
            return

        self._discover_items_in_dir(self.base_dir, prefix="")
        self.preload_handlers()

        active_names = set(self._items.keys())
        self._stats = {
            name: self._stats.get(name, SkillStats()) for name in active_names
        }

        item_names = sorted(self._items.keys())
        failed_names = {name for name, item in self._items.items() if item.load_error}
        ok_names = [name for name in item_names if name not in failed_names]
        # 计数与列表必须同源：get_schema() 已排除加载失败项，这里只能用成功项
        logger.info(
            "[%s] 成功加载了 %d 个项目: %s",
            self.__class__.__name__,
            len(ok_names),
            ", ".join(ok_names),
        )
        if failed_names:
            logger.warning(
                "[%s] %d 个项目加载失败，已排除: %s",
                self.__class__.__name__,
                len(failed_names),
                ", ".join(name for name in item_names if name in failed_names),
            )

    def _discover_items_in_dir(self, parent_dir: Path, prefix: str) -> None:
        for item in parent_dir.iterdir():
            if item.is_dir() and not item.name.startswith("_"):
                self._register_item_from_dir(item, prefix=prefix)

    def _register_item_from_dir(self, item_dir: Path, prefix: str = "") -> None:
        """从特定目录解析并注册一个技能项

        该方法会查找目录下的 config.json 和 handler.py，并构造 SkillItem。

        参数:
            item_dir: 技能所在的目录路径
            prefix: 技能名称的前缀（用于命名隔离）
        """
        config_path = item_dir / "config.json"
        handler_path = item_dir / "handler.py"

        if not config_path.exists() or not handler_path.exists():
            logger.debug(f"目录 {item_dir} 缺少 config.json 或 handler.py，跳过")
            return

        try:
            config = self._load_config(config_path)
            if not config:
                return

            item = self._build_skill_item(item_dir, config, handler_path, prefix)
            self._items[item.name] = item
            self._stats.setdefault(item.name, SkillStats())

            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "[%s加载] name=%s module=%s path=%s",
                    self.kind,
                    item.name,
                    item.module_name,
                    handler_path,
                )
                log_debug_json(logger, f"[{self.kind}配置] {item.name}", config)

        except Exception as e:
            logger.error(f"从 {item_dir} 加载失败: {e}")

    def _load_config(self, config_path: Path) -> Optional[Dict[str, Any]]:
        """加载并验证配置文件"""
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
            if not isinstance(config, dict) or "name" not in config.get("function", {}):
                logger.error(f"配置无效 {config_path.parent}: 缺少 function.name")
                return None
            return dict(config)
        except Exception as e:
            logger.error(f"加载配置文件失败 {config_path}: {e}")
            return None

    def _build_skill_item(
        self, item_dir: Path, config: Dict[str, Any], handler_path: Path, prefix: str
    ) -> SkillItem:
        """构建 SkillItem 对象"""
        original_name = config["function"]["name"]
        full_name = f"{prefix}{original_name}"

        if prefix:
            import copy

            config = copy.deepcopy(config)
            config["function"]["name"] = full_name

        module_name = self._build_module_name(item_dir)
        return SkillItem(
            name=full_name,
            config=config,
            handler_path=handler_path,
            module_name=module_name,
        )

    def _build_module_name(self, item_dir: Path) -> str:
        """合成 handler 的模块名。

        随包技能形如 ``Undefined.skills.agents.code_delivery_agent.handler``：
        父包真实存在，因此 handler.py 内的相对导入（``from .docker_utils import``）
        可以正常解析到同目录模块。不随包的目录（测试或外部注入）使用独立前缀，
        避免污染真实包命名空间。
        """
        try:
            relative = item_dir.relative_to(self.skills_root)
        except ValueError:
            relative = Path(*item_dir.parts[-3:])
        prefix = (
            _PACKAGE_PREFIX if _is_under_real_package(item_dir) else _SYNTHETIC_PREFIX
        )
        return ".".join([*prefix.split("."), *relative.parts, "handler"])

    def _load_handler_for_item(
        self, item: SkillItem, reload_module: bool = False
    ) -> None:
        """动态导入技能的 handler.py 模块并获取其 execute 函数"""
        if item.handler is not None and not reload_module:
            return

        if not item.handler_path or not item.module_name:
            return

        module = self._resolve_handler_module(item)
        if not hasattr(module, "execute"):
            item.load_error = "RuntimeError: 处理器缺少 'execute' 函数"
            raise RuntimeError(f"{item.handler_path} 的处理器缺少 'execute' 函数")

        item.handler = module.execute
        item.loaded = True
        item.load_error = None

    def _resolve_handler_module(self, item: SkillItem) -> Any:
        """取得 handler 的模块对象；失败时给 item 记上 load_error。"""
        assert item.module_name is not None and item.handler_path is not None
        try:
            if _is_under_real_package(item.handler_path.parent):
                return self._import_packaged_handler(
                    item.module_name, item.handler_path
                )
            return self._exec_handler_from_path(item.module_name, item.handler_path)
        except Exception as exc:
            item.load_error = f"{type(exc).__name__}: {exc}"
            raise

    def _import_packaged_handler(self, module_name: str, handler_path: Path) -> Any:
        """按真实包路径导入 handler。

        走标准 import 机制（而不是按文件路径注册），这样同一份源码只有一份模块
        对象：handler.py 内的相对导入能沿真实包链解析，其他位置的常规 import 也
        不会拿到重复状态。
        """
        self._purge_submodules(module_name)
        current = sys.modules.get(module_name)
        if current is None:
            return importlib.import_module(module_name)
        # 已有模块对象时按文件重新执行：热重载与首次加载都以磁盘内容为准，
        # 同时保留模块对象身份，外部持有的引用不会指向另一份模块状态。
        try:
            return importlib.reload(current)
        except Exception:
            logger.warning(
                "[%s] reload 处理器失败，改为按文件重新导入: %s",
                self.__class__.__name__,
                module_name,
                exc_info=True,
            )
            return self._exec_handler_from_path(module_name, handler_path)

    @staticmethod
    def _exec_handler_from_path(module_name: str, handler_path: Path) -> Any:
        """按文件路径导入不随包发布的 handler（测试或外部目录）。"""
        spec = importlib.util.spec_from_file_location(module_name, handler_path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"加载处理器 spec 失败: {handler_path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        try:
            spec.loader.exec_module(module)
        except Exception:
            if sys.modules.get(module_name) is module:
                del sys.modules[module_name]
            raise
        return module

    @staticmethod
    def _purge_submodules(module_name: str) -> None:
        """清理 handler 同目录相对导入产生的子模块缓存。

        `handler.py` 内的 `from .xxx import ...` 会把同目录模块注册成
        `<父包>.<模块>`；热重载时要一并失效，否则仍会使用旧代码。
        """
        package_name = module_name.rpartition(".")[0]
        parent_prefix = f"{package_name}."
        stale = [
            name
            for name in sys.modules
            if not name.endswith(".handler") and name.startswith(parent_prefix)
        ]
        for name in stale:
            sys.modules.pop(name, None)

    def preload_handlers(self) -> List[tuple[str, str]]:
        """在注册阶段导入全部 handler，尽早暴露加载失败。

        失败的项会被记录 `load_error` 并从对外 schema 中排除，避免主 AI
        被告知一个实际不可用的技能。返回 `(技能名, 错误)` 列表。
        """
        failures: List[tuple[str, str]] = []
        for name, item in self._items.items():
            if item.handler is not None:
                continue
            try:
                self._load_handler_for_item(item)
            except Exception as exc:
                if not item.load_error:
                    item.load_error = f"{type(exc).__name__}: {exc}"
            if item.load_error:
                failures.append((name, item.load_error))

        if failures:
            logger.error(
                "[%s] %s 个技能加载失败，已从工具列表中排除:",
                self.__class__.__name__,
                len(failures),
            )
            for name, error in failures:
                logger.error("  - %s: %s", name, error)
        return failures

    def get_load_failures(self) -> Dict[str, str]:
        """返回 handler 加载失败的技能名与错误信息。"""
        return {
            name: item.load_error
            for name, item in self._items.items()
            if item.load_error
        }

    def register_external_item(
        self,
        name: str,
        schema: Dict[str, Any],
        handler: Callable[[Dict[str, Any], Dict[str, Any]], Awaitable[Any]],
    ) -> None:
        """从外部（非文件系统发现）注册一个技能项

        常用于注册动态生成的工具或 MCP 注入的工具。

        参数:
            name: 技能名称
            schema: 符合相关协议的配置定义
            handler: 执行的具体回调函数
        """
        item = SkillItem(
            name=name,
            config=schema,
            handler_path=None,
            module_name=None,
            handler=handler,
            loaded=True,
        )
        self._items[name] = item
        self._stats.setdefault(name, SkillStats())

    def get_schema(self) -> List[Dict[str, Any]]:
        """返回可用技能的 schema；handler 加载失败的项不对外暴露。"""
        return [item.config for item in self._items.values() if not item.load_error]

    def get_stats(self) -> Dict[str, SkillStats]:
        return self._stats

    async def execute(
        self, name: str, args: Dict[str, Any], context: Dict[str, Any]
    ) -> str:
        """Execute a skill and convert failures to user-facing result strings."""
        return await self._execute(name, args, context, strict=False)

    async def execute_strict(
        self, name: str, args: Dict[str, Any], context: Dict[str, Any]
    ) -> str:
        """Execute a skill while preserving failures for workflow orchestration."""
        return await self._execute(name, args, context, strict=True)

    async def _execute(
        self,
        name: str,
        args: Dict[str, Any],
        context: Dict[str, Any],
        *,
        strict: bool,
    ) -> str:
        """执行指定的技能，包含超时控制、异常处理及统计记录

        参数:
            name: 技能名称
            args: 此调用传入的参数字典
            context: 调用执行的上下文环境

        返回:
            执行结果的字符串表示
        """
        args = parse_tool_arguments(args, logger=logger, tool_name=name)
        async with self._items_lock:
            item = self._items.get(name)

        if not item:
            if logger.isEnabledFor(logging.INFO) and self.kind in {
                "tool",
                "agent_tool",
                "agent",
            }:
                logger.info(
                    "[%s调用] %s 参数=%s",
                    self.kind,
                    name,
                    format_log_payload(args),
                )
                logger.info(
                    "[%s返回] %s 结果=%s",
                    self.kind,
                    name,
                    format_log_payload(f"未找到项目: {name}"),
                )
            if strict:
                raise LookupError(f"未找到项目: {name}")
            return f"未找到项目: {name}"

        if logger.isEnabledFor(logging.INFO) and self.kind in {
            "tool",
            "agent_tool",
            "agent",
        }:
            logger.info(
                "[%s调用] %s 参数=%s",
                self.kind,
                name,
                format_log_payload(args),
            )

        start_time = time.monotonic()
        result_payload: Any
        try:
            if logger.isEnabledFor(logging.DEBUG):
                log_debug_json(logger, f"[{self.kind}参数] {name}", args)
                logger.debug(
                    "[%s上下文] %s",
                    self.kind,
                    ", ".join(sorted(context.keys())),
                )
            if item.handler is None and item.handler_path:
                self._load_handler_for_item(item)
            handler = item.handler
            if not handler:
                if strict:
                    raise RuntimeError(f"未找到项目处理器: {name}")
                result_payload = f"未找到项目: {name}"
                return_value = str(result_payload)
            else:
                result = await self._execute_with_timeout(handler, args, context)
                duration = time.monotonic() - start_time

                self._stats[name].record_success(duration)
                self._log_event(
                    "execute", name, status="success", duration_ms=int(duration * 1000)
                )
                if logger.isEnabledFor(logging.DEBUG):
                    log_debug_json(logger, f"[{self.kind}结果] {name}", result)
                result_payload = result
                return_value = str(result)

        except RegistryExecutionTimeoutError:
            duration = time.monotonic() - start_time
            self._stats[name].record_failure(duration, "timeout")
            self._log_event(
                "execute", name, status="timeout", duration_ms=int(duration * 1000)
            )
            result_payload = f"执行 {name} 超时 (>{int(self.timeout_seconds)}s)"
            if strict:
                raise
            return_value = str(result_payload)

        except asyncio.CancelledError:
            duration = time.monotonic() - start_time
            self._stats[name].record_failure(duration, "cancelled")
            self._log_event(
                "execute", name, status="cancelled", duration_ms=int(duration * 1000)
            )
            result_payload = f"执行 {name} 已取消"
            if strict:
                raise
            return_value = str(result_payload)

        except Exception as e:
            duration = time.monotonic() - start_time
            self._stats[name].record_failure(duration, str(e))
            logger.exception(f"[执行异常] {name}")
            self._log_event(
                "execute", name, status="error", duration_ms=int(duration * 1000)
            )
            result_payload = f"执行 {name} 时出错: {str(e)}"
            if strict:
                raise
            return_value = str(result_payload)

        if logger.isEnabledFor(logging.INFO) and self.kind in {
            "tool",
            "agent_tool",
            "agent",
        }:
            logger.info(
                "[%s返回] %s 结果=%s",
                self.kind,
                name,
                format_log_payload(result_payload),
            )
        return return_value

    async def _execute_with_timeout(
        self,
        handler: Callable[[Dict[str, Any], Dict[str, Any]], Awaitable[Any]],
        args: Dict[str, Any],
        context: Dict[str, Any],
    ) -> Any:
        if not self._has_timeout():
            if asyncio.iscoroutinefunction(handler):
                return await handler(args, context)
            return await asyncio.to_thread(handler, args, context)

        if asyncio.iscoroutinefunction(handler):
            try:
                return await asyncio.wait_for(
                    handler(args, context), timeout=self.timeout_seconds
                )
            except asyncio.TimeoutError as exc:
                raise RegistryExecutionTimeoutError from exc
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(handler, args, context), timeout=self.timeout_seconds
            )
        except asyncio.TimeoutError as exc:
            raise RegistryExecutionTimeoutError from exc

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
            try:
                from Undefined.context_resource_registry import (
                    refresh_context_resource_keys,
                )

                refresh_context_resource_keys()
            except Exception:
                logger.debug("刷新上下文资源键缓存失败", exc_info=True)

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
