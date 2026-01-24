import json
import logging
import importlib.util
import asyncio
from pathlib import Path
from typing import Dict, Any, List, Callable, Awaitable

logger = logging.getLogger(__name__)


class BaseRegistry:
    """
    基础注册表类，用于发现和加载技能（Tools/Agents）。

    提供统一的加载、验证和执行逻辑。
    """

    def __init__(self, base_dir: Path | str | None = None):
        """
        初始化注册表。

        参数:
            base_dir: 基础目录路径。如果为 None，子类应在自己的 init 中设置或调用 load 时指定。
        """
        if base_dir:
            self.base_dir = Path(base_dir)
        else:
            self.base_dir = Path(".")  # 默认当前目录，应由子类覆盖

        self._items_schema: List[Dict[str, Any]] = []
        self._items_handlers: Dict[
            str, Callable[[Dict[str, Any], Dict[str, Any]], Awaitable[Any]]
        ] = {}

    def load_items(self) -> None:
        """从 base_dir 自动发现并加载项。"""
        self._items_schema = []
        self._items_handlers = {}

        if not self.base_dir.exists():
            logger.warning(f"目录不存在: {self.base_dir}")
            return

        # 遍历目录
        for item in self.base_dir.iterdir():
            if item.is_dir() and not item.name.startswith("_"):
                self._load_item_from_dir(item)

        item_names = list(self._items_handlers.keys())
        logger.info(
            f"[{self.__class__.__name__}] 成功加载了 {len(self._items_schema)} 个项目: {', '.join(item_names)}"
        )

    def _load_item_from_dir(self, item_dir: Path, prefix: str = "") -> None:
        """
        从指定目录加载单个项 (Tool/Agent)。

        参数:
            item_dir: 项目目录
            prefix: 名称前缀 (例如 "scheduler.")
        """
        config_path = item_dir / "config.json"
        handler_path = item_dir / "handler.py"

        if not config_path.exists() or not handler_path.exists():
            # 只有当两个都存在时才尝试加载，否则 silently skip (但 debug log)
            logger.debug(f"目录 {item_dir} 缺少 config.json 或 handler.py，跳过")
            return

        try:
            # 加载配置
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)

            # 验证配置
            if "name" not in config.get("function", {}):
                logger.error(f"配置无效 {item_dir}: 缺少 function.name")
                return

            original_name = config["function"]["name"]
            # 应用前缀
            full_name = f"{prefix}{original_name}"

            # 为了避免修改原始 config 字典导致的问题（如果有缓存），复制一份
            # 但这里我们主要修改 schema，所以确保 schema 里的 name 是带前缀的
            if prefix:
                # 浅拷贝 function dict 以修改 name
                # 注意：如果 config 结构复杂，可能需要 deepcopy
                import copy

                config = copy.deepcopy(config)
                config["function"]["name"] = full_name

            logger.debug(f"正在加载: {full_name} from {item_dir}")

            # 加载处理器 (Handler)
            # 构造一个唯一的模块名，避免 sys.modules 冲突
            # 使用 relative path parts 作为模块名的一部分
            # 例如: skills.tools.my_tool
            # 如果我们不能确定 parent package，就用 unique string

            # 尝试构造有意义的模块名
            # 假设 path 是 .../skills/tools/myurl
            # parts[-3:] -> ('skills', 'tools', 'myurl')
            module_name_parts = item_dir.parts[-3:]
            module_name = ".".join(module_name_parts)

            spec = importlib.util.spec_from_file_location(module_name, handler_path)
            if spec is None or spec.loader is None:
                logger.error(f"加载处理器 spec 失败: {handler_path}")
                return

            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            if not hasattr(module, "execute"):
                logger.error(f"{item_dir} 的处理器缺少 'execute' 函数")
                return

            self._items_schema.append(config)
            self._items_handlers[full_name] = module.execute

        except Exception as e:
            logger.error(f"从 {item_dir} 加载失败: {e}")

    def get_schema(self) -> List[Dict[str, Any]]:
        """获取所有已加载项的 Schema。"""
        return self._items_schema

    async def execute(
        self, name: str, args: Dict[str, Any], context: Dict[str, Any]
    ) -> str:
        """
        执行指定名称的项目。
        """
        handler = self._items_handlers.get(name)
        if not handler:
            return f"未找到项目: {name}"

        try:
            # 检查 handler 是否是协程
            # 注意：asyncio.iscoroutinefunction 对某些 callable 可能判断不准，
            # 但在这里 handler 通常是 function

            start_time = asyncio.get_event_loop().time()

            if asyncio.iscoroutinefunction(handler):
                result = await handler(args, context)
            else:
                # 支持同步函数作为 fallback
                result = handler(args, context)

            duration = asyncio.get_event_loop().time() - start_time
            logger.info(f"[执行成功] {name} 耗时={duration:.4f}s")
            return str(result)

        except Exception as e:
            logger.exception(f"[执行异常] {name}")
            return f"执行 {name} 时出错: {str(e)}"
