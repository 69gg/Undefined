import logging
from pathlib import Path
from typing import Dict, Any, List

from Undefined.skills.registry import BaseRegistry, SkillStats

logger = logging.getLogger(__name__)


class ToolSetRegistry(BaseRegistry):
    """兼容的 ToolSetRegistry（基于统一加载器）"""

    def __init__(self, toolsets_dir: str | Path | None = None):
        if toolsets_dir is None:
            toolsets_path = Path(__file__).parent
        else:
            toolsets_path = Path(toolsets_dir)

        super().__init__(toolsets_path, kind="toolset")
        self.load_toolsets()

    def load_toolsets(self) -> None:
        self._reset_items()
        if not self.base_dir.exists():
            logger.warning(f"工具集目录不存在: {self.base_dir}")
            return

        for category_dir in self.base_dir.iterdir():
            if not category_dir.is_dir() or category_dir.name.startswith("_"):
                continue
            category = category_dir.name
            self._discover_items_in_dir(category_dir, prefix=f"{category}.")

        active_names = set(self._items.keys())
        self._stats = {
            name: self._stats.get(name, SkillStats()) for name in active_names
        }

        tool_names = list(self._items.keys())
        logger.info(
            f"成功加载了 {len(self._items_schema)} 个工具集工具: {', '.join(tool_names)}"
        )

    def get_tools_schema(self) -> List[Dict[str, Any]]:
        return self.get_schema()

    async def execute_tool(
        self, tool_name: str, args: Dict[str, Any], context: Dict[str, Any]
    ) -> str:
        return await self.execute(tool_name, args, context)
