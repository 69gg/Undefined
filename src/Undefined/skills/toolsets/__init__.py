import json
import logging
import importlib.util
import asyncio
from pathlib import Path
from typing import Dict, Any, List, Callable, Awaitable

logger = logging.getLogger(__name__)


class ToolSetRegistry:
    def __init__(self, toolsets_dir: str | Path | None = None):
        if toolsets_dir is None:
            # 默认为此文件所在的目录
            self.toolsets_dir = Path(__file__).parent
        else:
            self.toolsets_dir = Path(toolsets_dir)

        self._tools_schema: List[Dict[str, Any]] = []
        self._tools_handlers: Dict[
            str, Callable[[Dict[str, Any], Dict[str, Any]], Awaitable[Any]]
        ] = {}
        self.load_toolsets()

    def load_toolsets(self) -> None:
        """从 toolsets 目录发现并加载工具集。"""
        self._tools_schema = []
        self._tools_handlers = {}

        if not self.toolsets_dir.exists():
            logger.warning(f"工具集目录不存在: {self.toolsets_dir}")
            return

        # 遍历分类目录 (例如 scheduler)
        for category_dir in self.toolsets_dir.iterdir():
            if category_dir.is_dir() and not category_dir.name.startswith("_"):
                self._load_category(category_dir)

        tool_names = list(self._tools_handlers.keys())
        logger.info(
            f"成功加载了 {len(self._tools_schema)} 个工具集工具: {', '.join(tool_names)}"
        )

    def _load_category(self, category_dir: Path) -> None:
        """加载单个分类下的所有工具。"""
        category_name = category_dir.name
        # 遍历该分类下的工具目录
        for tool_dir in category_dir.iterdir():
            if tool_dir.is_dir() and not tool_dir.name.startswith("_"):
                self._load_tool(tool_dir, category_name)

    def _load_tool(self, tool_dir: Path, category_name: str) -> None:
        """加载单个工具并在名称前添加分类前缀。"""
        config_path = tool_dir / "config.json"
        handler_path = tool_dir / "handler.py"

        if not config_path.exists() or not handler_path.exists():
            logger.debug(
                f"[工具集加载] 目录 {tool_dir} 缺少 config.json 或 handler.py，跳过"
            )
            return

        # 加载配置
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)

            # 基本验证
            if "name" not in config.get("function", {}):
                logger.error(
                    f"[工具集错误] 工具配置无效 {tool_dir}: 缺少 function.name"
                )
                return

            original_name = config["function"]["name"]
            # 添加前缀: category.original_name
            new_name = f"{category_name}.{original_name}"

            # 这里的修改需要注意，不能直接修改 dict 引用，否则可能会影响后续重载
            # 创建一个新的 config 副本
            new_config = json.loads(json.dumps(config))
            new_config["function"]["name"] = new_name

            logger.debug(f"[工具集加载] 正在从 {tool_dir} 加载工具: {new_name}")

        except Exception as e:
            logger.error(f"[工具集错误] 从 {tool_dir} 加载工具配置失败: {e}")
            return

        # 加载处理器
        try:
            # 使用唯一的模块名称以避免冲突
            module_name = f"skills.toolsets.{category_name}.{original_name}"
            spec = importlib.util.spec_from_file_location(module_name, handler_path)
            if spec is None or spec.loader is None:
                logger.error(f"从 {handler_path} 加载工具处理器 spec 失败")
                return

            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            if not hasattr(module, "execute"):
                logger.error(f"工具 {tool_dir} 的处理器缺少 'execute' 函数")
                return

            self._tools_schema.append(new_config)
            self._tools_handlers[new_name] = module.execute

        except Exception as e:
            logger.error(f"从 {tool_dir} 加载工具处理器失败: {e}")

    def get_tools_schema(self) -> List[Dict[str, Any]]:
        """返回 AI 模型的工具定义列表。"""
        return self._tools_schema

    async def execute_tool(
        self, tool_name: str, args: Dict[str, Any], context: Dict[str, Any]
    ) -> str:
        """根据名称执行工具。"""
        handler = self._tools_handlers.get(tool_name)
        if not handler:
            return f"未找到工具: {tool_name}"

        try:
            # 检查处理器是否为协程
            start_time = asyncio.get_event_loop().time()
            if asyncio.iscoroutinefunction(handler):
                result = await handler(args, context)
            else:
                # 我们预期工具是异步的，但也支持同步以防万一
                result = handler(args, context)

            duration = asyncio.get_event_loop().time() - start_time
            logger.info(f"[工具集执行] {tool_name} 执行成功, 耗时={duration:.4f}s")
            return str(result)
        except Exception as e:
            logger.exception(f"[工具集异常] 执行工具 {tool_name} 时出错")
            return f"执行工具 {tool_name} 时出错: {str(e)}"
