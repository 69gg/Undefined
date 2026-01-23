import json
import logging
import importlib.util
import asyncio
from pathlib import Path
from typing import Dict, Any, List, Callable, Awaitable

logger = logging.getLogger(__name__)


class ToolRegistry:
    def __init__(self, tools_dir: str | Path | None = None):
        if tools_dir is None:
            # 默认为此文件所在的目录
            self.tools_dir = Path(__file__).parent
        else:
            self.tools_dir = Path(tools_dir)

        self._tools_schema: List[Dict[str, Any]] = []
        self._tools_handlers: Dict[
            str, Callable[[Dict[str, Any], Dict[str, Any]], Awaitable[Any]]
        ] = {}
        self.load_tools()

    def load_tools(self) -> None:
        """从 tools 目录发现并加载工具。"""
        self._tools_schema = []
        self._tools_handlers = {}

        if not self.tools_dir.exists():
            logger.warning(f"工具目录不存在: {self.tools_dir}")
            return

        for item in self.tools_dir.iterdir():
            if item.is_dir() and not item.name.startswith("_"):
                self._load_tool_from_dir(item)

        tool_names = list(self._tools_handlers.keys())
        logger.info(
            f"成功加载了 {len(self._tools_schema)} 个工具: {', '.join(tool_names)}"
        )

        # 加载 Skills (toolsets)
        self.toolsets_dir = self.tools_dir.parent / "toolsets"
        self.load_toolsets()

    def load_toolsets(self) -> None:
        """从 toolsets 目录发现并加载工具集。

        目录结构: toolsets/{skill_name}/{category}/{tool_name}
        注册名称: {skill_name}.{tool_name}
        """
        if not self.toolsets_dir.exists():
            logger.debug(f"Toolsets directory not found: {self.toolsets_dir}")
            return

        for skill_dir in self.toolsets_dir.iterdir():
            if not skill_dir.is_dir() or skill_dir.name.startswith("_"):
                continue

            skill_name = skill_dir.name
            logger.info(f"发现 Skill.toolsets: {skill_name}")

            # 遍历分类目录
            for category_dir in skill_dir.iterdir():
                if not category_dir.is_dir() or category_dir.name.startswith("_"):
                    continue

                logger.debug(f"发现 Skill 分类: {category_dir.name} (归属于 {skill_name})")

                # 遍历工具目录
                for tool_dir in category_dir.iterdir():
                    if not tool_dir.is_dir() or tool_dir.name.startswith("_"):
                        continue

                    self._load_tool_from_dir(tool_dir, prefix=f"{skill_name}.")

    def _load_tool_from_dir(self, tool_dir: Path, prefix: str = "") -> None:
        """从目录加载单个工具。"""
        config_path = tool_dir / "config.json"
        handler_path = tool_dir / "handler.py"

        if not config_path.exists() or not handler_path.exists():
            logger.debug(
                f"[工具加载] 目录 {tool_dir} 缺少 config.json 或 handler.py，跳过"
            )
            return

        # 加载配置
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)

            # 基本验证
            if "name" not in config.get("function", {}):
                logger.error(f"[工具错误] 工具配置无效 {tool_dir}: 缺少 function.name")
                return

            original_tool_name = config["function"]["name"]
            tool_name = f"{prefix}{original_tool_name}"

            # 如果有前缀，更新 name
            if prefix:
                config["function"]["name"] = tool_name

            logger.debug(f"[工具加载] 正在从 {tool_dir} 加载工具: {tool_name}")

        except Exception as e:
            logger.error(f"[工具错误] 从 {tool_dir} 加载工具配置失败: {e}")
            return

        # 加载处理器
        try:
            # 使用唯一名称注册模块，避免冲突
            module_name = (
                f"skills.toolsets.{tool_name}" if prefix else f"tools.{tool_name}"
            )
            spec = importlib.util.spec_from_file_location(module_name, handler_path)
            if spec is None or spec.loader is None:
                logger.error(f"从 {handler_path} 加载工具处理器 spec 失败")
                return

            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            if not hasattr(module, "execute"):
                logger.error(f"工具 {tool_dir} 的处理器缺少 'execute' 函数")
                return

            self._tools_schema.append(config)
            self._tools_handlers[tool_name] = module.execute

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
                # 注意：我们的类型提示是 Awaitable，所以这只是为了安全
                result = handler(args, context)

            duration = asyncio.get_event_loop().time() - start_time
            logger.info(f"[工具执行] {tool_name} 执行成功, 耗时={duration:.4f}s")
            return str(result)
        except Exception as e:
            logger.exception(f"[工具异常] 执行工具 {tool_name} 时出错")
            return f"执行工具 {tool_name} 时出错: {str(e)}"
