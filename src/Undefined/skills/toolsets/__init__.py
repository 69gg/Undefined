import logging
from pathlib import Path
from typing import Dict, Any, List

from Undefined.skills.registry import BaseRegistry, SkillStats

logger = logging.getLogger(__name__)


class ToolSetRegistry(BaseRegistry):
    """工具集注册中心

    负责按类别（category）加载、管理和执行各类工具集下的工具。
    继承自 BaseRegistry，提供热重载和统计功能。
    """

    def __init__(self, toolsets_dir: str | Path | None = None) -> None:
        """初始化工具集注册表

        参数:
            toolsets_dir: 工具集存放的根目录，默认为当前文件所在目录
        """
        if toolsets_dir is None:
            toolsets_path = Path(__file__).parent
        else:
            toolsets_path = Path(toolsets_dir)

        super().__init__(toolsets_path, kind="toolset")
        self.load_toolsets()

    def load_toolsets(self) -> None:
        """加载所有分类目录下的工具集项

        遍历 base_dir 下的子目录（分类），并加载每个分类中的工具定义和处理器。
        """
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
        """获取所有已加载工具的架构定义列表

        返回:
            OpenAI API 格式的工具定义列表
        """
        return self.get_schema()

    async def execute_tool(
        self, tool_name: str, args: Dict[str, Any], context: Dict[str, Any]
    ) -> str:
        """执行指定的工具

        参数:
            tool_name: 工具的全名 (包含分类前缀，如 'messages.send_message')
            args: 工具调用参数
            context: 执行上下文

        返回:
            工具执行结果的文本表示
        """
        return await self.execute(tool_name, args, context)
