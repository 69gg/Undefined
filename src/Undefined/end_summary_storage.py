"""End 摘要持久化存储模块"""

import logging
from pathlib import Path
from typing import List

logger = logging.getLogger(__name__)

# End 摘要数据存储路径
END_SUMMARIES_FILE_PATH = Path("data/end_summaries.json")


class EndSummaryStorage:
    """End 摘要存储管理器"""

    def __init__(self) -> None:
        """初始化存储"""
        pass

    async def save(self, summaries: List[str]) -> None:
        """保存所有摘要到文件"""
        try:
            from Undefined.utils import io

            await io.write_json(END_SUMMARIES_FILE_PATH, summaries, use_lock=True)
            logger.debug(f"已保存 {len(summaries)} 条 End 摘要")
        except Exception as e:
            logger.error(f"保存 End 摘要数据失败: {e}")

    async def load(self) -> List[str]:
        """从文件加载所有摘要 (异步)"""
        from Undefined.utils import io

        data = await io.read_json(END_SUMMARIES_FILE_PATH, use_lock=False)

        if data is None:
            return []

        if isinstance(data, list):
            return data
        else:
            logger.warning(f"End 摘要数据格式异常，期望 list，实际得到 {type(data)}")
            return []
