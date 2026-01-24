import logging
from pathlib import Path
from typing import Dict, Any, List, TYPE_CHECKING

from ..registry import BaseRegistry

if TYPE_CHECKING:
    from ..toolsets.mcp import MCPToolSetRegistry

logger = logging.getLogger(__name__)


class ToolRegistry(BaseRegistry):
    def __init__(self, tools_dir: str | Path | None = None):
        if tools_dir is None:
            # 默认为此文件所在的目录
            tools_path = Path(__file__).parent
        else:
            tools_path = Path(tools_dir)

        super().__init__(tools_path)

        # 初始化 MCP 工具集注册表
        self._mcp_registry: MCPToolSetRegistry | None = None

        # 自动加载
        self.load_tools()

    def load_tools(self) -> None:
        """从 tools 目录发现并加载工具，同时也加载 toolsets 和 MCP 工具集。"""
        # 1. 加载 tools 目录下的非分类工具
        self.load_items()

        # 2. 加载 Skills (toolsets)
        # 假设 toolsets 位于 tools 的同级目录
        self.toolsets_dir = self.base_dir.parent / "toolsets"
        self._load_toolsets_recursive()

        # 3. 加载 MCP 工具集（创建注册表，但不初始化）
        self._load_mcp_toolsets()

        # 4. 输出工具列表（不包含 MCP 工具，因为 MCP 还未初始化）
        self._log_tools_summary(include_mcp=False)

    def _log_tools_summary(self, include_mcp: bool = True) -> None:
        """输出工具加载统计

        参数:
            include_mcp: 是否包含 MCP 工具
        """
        tool_names = list(self._items_handlers.keys())
        basic_tools = [name for name in tool_names if "." not in name]
        toolset_tools = [
            name for name in tool_names if "." in name and not name.startswith("mcp.")
        ]
        mcp_tools = [name for name in tool_names if name.startswith("mcp.")]

        # 按 toolsets 分类整理
        toolset_by_category: Dict[str, List[str]] = {}
        for name in toolset_tools:
            category = name.split(".")[0]
            if category not in toolset_by_category:
                toolset_by_category[category] = []
            toolset_by_category[category].append(name)

        if mcp_tools and include_mcp:
            logger.info("=" * 60)
            if include_mcp:
                logger.info("工具加载完成统计")
            else:
                logger.info("工具加载完成统计（MCP 工具待初始化）")
            logger.info(
                f"  - 基础工具 ({len(basic_tools)} 个): {', '.join(basic_tools) if basic_tools else '无'}"
            )
            if toolset_by_category:
                logger.info(f"  - 工具集工具 ({len(toolset_tools)} 个):")
                for category, tools in sorted(toolset_by_category.items()):
                    logger.info(
                        f"    [{category}] ({len(tools)} 个): {', '.join(tools)}"
                    )
            # if mcp_tools and include_mcp:
            logger.info(f"  - MCP 工具 ({len(mcp_tools)} 个): {', '.join(mcp_tools)}")
            # elif not include_mcp and hasattr(self, "_mcp_registry") and self._mcp_registry:
            # logger.info("  - MCP 工具: (等待异步初始化...)")
            logger.info(f"  - 总计: {len(tool_names)} 个工具")
            logger.info("=" * 60)

    def _load_toolsets_recursive(self) -> None:
        """从 toolsets 目录发现并加载工具集。

        目录结构: toolsets/{category}/{tool_name}
        注册名称: {category}.{tool_name}
        """
        if not self.toolsets_dir.exists():
            logger.debug(f"Toolsets directory not found: {self.toolsets_dir}")
            return

        for category_dir in self.toolsets_dir.iterdir():
            if not category_dir.is_dir() or category_dir.name.startswith("_"):
                continue

            category_name = category_dir.name
            logger.debug(f"发现 toolsets 分类: {category_name}")

            # 遍历该分类下的工具目录
            for tool_dir in category_dir.iterdir():
                if not tool_dir.is_dir() or tool_dir.name.startswith("_"):
                    continue

                # 使用基类方法加载，指定前缀
                self._load_item_from_dir(tool_dir, prefix=f"{category_name}.")

    def _load_mcp_toolsets(self) -> None:
        """加载 MCP 工具集（创建注册表，但不初始化）"""
        try:
            from ..toolsets.mcp import MCPToolSetRegistry

            # 创建 MCP 工具集注册表
            self._mcp_registry = MCPToolSetRegistry()
            logger.info("MCP 工具集注册表已创建（待初始化）")

        except ImportError as e:
            logger.warning(f"无法导入 MCP 工具集注册表: {e}")
            self._mcp_registry = None

    async def initialize_mcp_toolsets(self) -> None:
        """异步初始化 MCP 工具集

        需要在 AIClient 初始化后调用。
        """
        if hasattr(self, "_mcp_registry") and self._mcp_registry:
            try:
                await self._mcp_registry.initialize()

                # 将 MCP 工具添加到主注册表
                for schema in self._mcp_registry.get_tools_schema():
                    self._items_schema.append(schema)

                for tool_name, handler in self._mcp_registry._tools_handlers.items():
                    self._items_handlers[tool_name] = handler

                logger.info(
                    f"MCP 工具集已集成到主注册表，共 {len(self._mcp_registry._tools_handlers)} 个工具"
                )

                # 输出包含 MCP 工具的完整统计
                self._log_tools_summary(include_mcp=True)

            except Exception as e:
                logger.exception(f"初始化 MCP 工具集失败: {e}")

    async def close_mcp_toolsets(self) -> None:
        """关闭 MCP 工具集连接"""
        if hasattr(self, "_mcp_registry") and self._mcp_registry:
            try:
                await self._mcp_registry.close()
            except Exception as e:
                logger.warning(f"关闭 MCP 工具集时出错: {e}")

    # --- 兼容性别名 ---

    def get_tools_schema(self) -> List[Dict[str, Any]]:
        """返回 AI 模型的工具定义列表。"""
        return self.get_schema()

    async def execute_tool(
        self, tool_name: str, args: Dict[str, Any], context: Dict[str, Any]
    ) -> str:
        """根据名称执行工具。"""
        return await self.execute(tool_name, args, context)
