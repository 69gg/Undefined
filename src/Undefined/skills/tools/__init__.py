import logging
from pathlib import Path
from typing import Dict, Any, List, TYPE_CHECKING

from Undefined.skills.registry import BaseRegistry, SkillStats

if TYPE_CHECKING:
    from Undefined.mcp import MCPToolRegistry

logger = logging.getLogger(__name__)


class ToolRegistry(BaseRegistry):
    def __init__(self, tools_dir: str | Path | None = None):
        if tools_dir is None:
            tools_path = Path(__file__).parent
        else:
            tools_path = Path(tools_dir)

        super().__init__(tools_path, kind="tool")

        self.toolsets_dir = self.base_dir.parent / "toolsets"
        self._mcp_registry: MCPToolRegistry | None = None
        self._mcp_initialized: bool = False

        self.set_watch_paths([self.base_dir, self.toolsets_dir])
        self.load_tools()

    def load_tools(self) -> None:
        """从 tools 目录发现并加载工具，同时也加载 toolsets 和 MCP 工具集。"""
        self._reset_items()

        # 1) tools 目录
        if self.base_dir.exists():
            self._discover_items_in_dir(self.base_dir, prefix="")
        else:
            logger.warning(f"目录不存在: {self.base_dir}")

        # 2) toolsets 目录
        self._load_toolsets_recursive()

        # 3) MCP 工具集（创建注册表，但不初始化）
        self._load_mcp_toolsets()

        active_names = set(self._items.keys())
        self._stats = {
            name: self._stats.get(name, SkillStats()) for name in active_names
        }

        # 4) 输出工具列表（不包含 MCP 工具，因为 MCP 还未初始化）
        self._log_tools_summary(include_mcp=False)

    def _categorize_tools(
        self, tool_names: list[str]
    ) -> tuple[list[str], list[str], list[str]]:
        """将工具按类型分类。

        Args:
            tool_names: 工具名称列表

        Returns:
            (基础工具列表, 工具集工具列表, MCP 工具列表)
        """
        basic_tools = [name for name in tool_names if "." not in name]
        toolset_tools = [
            name for name in tool_names if "." in name and not name.startswith("mcp.")
        ]
        mcp_tools = [name for name in tool_names if name.startswith("mcp.")]
        return basic_tools, toolset_tools, mcp_tools

    def _group_toolsets_by_category(
        self, toolset_tools: list[str]
    ) -> dict[str, list[str]]:
        """将工具集工具按类别分组。

        Args:
            toolset_tools: 工具集工具列表

        Returns:
            按类别分组的工具字典
        """
        toolset_by_category: dict[str, list[str]] = {}
        for name in toolset_tools:
            category = name.split(".")[0]
            toolset_by_category.setdefault(category, []).append(name)
        return toolset_by_category

    def _format_tools_list(self, tools: list[str]) -> str:
        """格式化工具列表为字符串。

        Args:
            tools: 工具列表

        Returns:
            格式化后的字符串
        """
        return ", ".join(tools) if tools else "无"

    def _log_toolset_category(self, category: str, tools: list[str]) -> None:
        """记录工具集类别的信息。

        Args:
            category: 类别名称
            tools: 该类别的工具列表
        """
        logger.info(f"    [{category}] ({len(tools)} 个): {', '.join(tools)}")

    def _log_tools_summary(self, include_mcp: bool = True) -> None:
        """记录工具加载完成统计信息。

        Args:
            include_mcp: 是否包含 MCP 工具
        """
        tool_names = list(self._items.keys())

        # 分类工具
        basic_tools, toolset_tools, mcp_tools = self._categorize_tools(tool_names)

        # 按类别分组工具集工具
        toolset_by_category = self._group_toolsets_by_category(toolset_tools)

        # 输出统计信息
        logger.info("=" * 60)
        if include_mcp:
            logger.info("工具加载完成统计 (包含 MCP)")
        else:
            logger.info("工具加载完成统计 (基础工具)")
        logger.info(
            f"  - 基础工具 ({len(basic_tools)} 个): {self._format_tools_list(basic_tools)}"
        )
        if toolset_by_category:
            logger.info(f"  - 工具集工具 ({len(toolset_tools)} 个):")
            for category, tools in sorted(toolset_by_category.items()):
                self._log_toolset_category(category, tools)
        if mcp_tools and include_mcp:
            logger.info(
                f"  - MCP 工具 ({len(mcp_tools)} 个): {self._format_tools_list(mcp_tools)}"
            )
        logger.info(f"  - 总计: {len(tool_names)} 个工具")
        logger.info("=" * 60)

    def _load_toolsets_recursive(self) -> None:
        """从 toolsets 目录发现并加载工具集。"""
        if not self.toolsets_dir.exists():
            logger.debug(f"Toolsets directory not found: {self.toolsets_dir}")
            return

        for category_dir in self.toolsets_dir.iterdir():
            if not category_dir.is_dir() or category_dir.name.startswith("_"):
                continue
            category_name = category_dir.name
            logger.debug(f"发现 toolsets 分类: {category_name}")
            self._discover_items_in_dir(category_dir, prefix=f"{category_name}.")

    def _load_mcp_toolsets(self) -> None:
        """加载 MCP 工具集（创建注册表，但不初始化）"""
        if self._mcp_registry is not None:
            return
        try:
            from Undefined.mcp import MCPToolRegistry

            self._mcp_registry = MCPToolRegistry()
            logger.info("MCP 工具集注册表已创建（待初始化）")

        except ImportError as e:
            logger.warning(f"无法导入 MCP 工具集注册表: {e}")
            self._mcp_registry = None

    def _apply_mcp_tools(self) -> None:
        if not self._mcp_registry:
            return
        logger.debug(
            "开始集成 MCP 工具: count=%s",
            len(self._mcp_registry.get_tools_schema()),
        )
        for schema in self._mcp_registry.get_tools_schema():
            name = schema.get("function", {}).get("name", "")
            handler = self._mcp_registry._tools_handlers.get(name)
            if name and handler:
                self.register_external_item(name, schema, handler)
                logger.debug("已集成 MCP 工具: %s", name)

    async def initialize_mcp_toolsets(self) -> None:
        """异步初始化 MCP 工具集"""
        if self._mcp_registry:
            try:
                await self._mcp_registry.initialize()
                self._mcp_initialized = True
                self._apply_mcp_tools()
                logger.info(
                    f"MCP 工具集已集成到主注册表，共 {len(self._mcp_registry._tools_handlers)} 个工具"
                )
                self._log_tools_summary(include_mcp=True)
            except Exception as e:
                logger.exception(f"初始化 MCP 工具集失败: {e}")

    async def close_mcp_toolsets(self) -> None:
        """关闭 MCP 工具集连接"""
        if self._mcp_registry:
            try:
                await self._mcp_registry.close()
            except Exception as e:
                logger.warning(f"关闭 MCP 工具集时出错: {e}")

    async def _reload_items(self) -> None:
        async with self._items_lock:
            self.load_tools()
            if self._mcp_registry and self._mcp_initialized:
                self._apply_mcp_tools()

    # --- 兼容性别名 ---

    def get_tools_schema(self) -> List[Dict[str, Any]]:
        return self.get_schema()

    async def execute_tool(
        self, tool_name: str, args: Dict[str, Any], context: Dict[str, Any]
    ) -> str:
        return await self.execute(tool_name, args, context)
