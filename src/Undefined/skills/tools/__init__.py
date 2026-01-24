import logging
from pathlib import Path
from typing import Dict, Any, List

from ..registry import BaseRegistry

logger = logging.getLogger(__name__)


class ToolRegistry(BaseRegistry):
    def __init__(self, tools_dir: str | Path | None = None):
        if tools_dir is None:
            # 默认为此文件所在的目录
            tools_path = Path(__file__).parent
        else:
            tools_path = Path(tools_dir)

        super().__init__(tools_path)

        # 自动加载
        self.load_tools()

    def load_tools(self) -> None:
        """从 tools 目录发现并加载工具，同时也加载 toolsets。"""
        # 1. 加载 tools 目录下的非分类工具
        self.load_items()

        # 2. 加载 Skills (toolsets)
        # 假设 toolsets 位于 tools 的同级目录
        self.toolsets_dir = self.base_dir.parent / "toolsets"
        self._load_toolsets_recursive()

        # 3. 输出详细的工具列表
        tool_names = list(self._items_handlers.keys())
        basic_tools = [name for name in tool_names if "." not in name]
        toolset_tools = [name for name in tool_names if "." in name]

        # 按 toolsets 分类整理
        toolset_by_category: Dict[str, List[str]] = {}
        for name in toolset_tools:
            category = name.split(".")[0]
            if category not in toolset_by_category:
                toolset_by_category[category] = []
            toolset_by_category[category].append(name)

        logger.info("=" * 60)
        logger.info("工具加载完成统计")
        logger.info(
            f"  - 基础工具 ({len(basic_tools)} 个): {', '.join(basic_tools) if basic_tools else '无'}"
        )
        if toolset_by_category:
            logger.info(f"  - 工具集工具 ({len(toolset_tools)} 个):")
            for category, tools in sorted(toolset_by_category.items()):
                logger.info(f"    [{category}] ({len(tools)} 个): {', '.join(tools)}")
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

    # --- 兼容性别名 ---

    def get_tools_schema(self) -> List[Dict[str, Any]]:
        """返回 AI 模型的工具定义列表。"""
        return self.get_schema()

    async def execute_tool(
        self, tool_name: str, args: Dict[str, Any], context: Dict[str, Any]
    ) -> str:
        """根据名称执行工具。"""
        return await self.execute(tool_name, args, context)
