"""FAQ 存储管理"""

import logging
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class FAQ:
    """FAQ 条目"""

    id: str
    group_id: int
    target_qq: int
    start_time: str
    end_time: str
    created_at: str
    title: str
    content: str

    def to_dict(self) -> dict[str, str | int]:
        """转换为字典"""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, str | int]) -> "FAQ":
        """从字典创建 FAQ"""
        return cls(**data)  # type: ignore


class FAQStorage:
    """FAQ 本地存储管理"""

    def __init__(self, base_dir: str = "data/faq") -> None:
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _get_group_dir(self, group_id: int) -> Path:
        """获取群组的 FAQ 存储目录

        参数:
            group_id: 群号

        返回:
            群组 FAQ 目录路径
        """
        group_dir = self.base_dir / str(group_id)
        group_dir.mkdir(parents=True, exist_ok=True)
        return group_dir

    def _generate_id(self, group_id: int) -> str:
        """生成新的 FAQ ID

        参数:
            group_id: 群号

        返回:
            新的 FAQ ID
        """
        group_dir = self._get_group_dir(group_id)
        existing = list(group_dir.glob("*.json"))

        # 使用时间戳 + 序号
        timestamp = datetime.now().strftime("%Y%m%d")
        count = sum(1 for f in existing if f.stem.startswith(timestamp))
        return f"{timestamp}-{count + 1:03d}"

    async def save(self, faq: FAQ) -> str:
        """保存 FAQ

        参数:
            faq: FAQ 条目

        返回:
            FAQ ID
        """
        group_dir = self._get_group_dir(faq.group_id)
        file_path = group_dir / f"{faq.id}.json"

        from Undefined.utils import io

        await io.write_json(file_path, faq.to_dict(), use_lock=True)

        logger.info(f"FAQ 已保存: {file_path}")
        return faq.id

    async def create(
        self,
        group_id: int,
        target_qq: int,
        start_time: str,
        end_time: str,
        title: str,
        content: str,
    ) -> FAQ:
        """创建新的 FAQ 条目

        参数:
            group_id: 群号
            target_qq: 目标 QQ 号
            start_time: 开始时间
            end_time: 结束时间
            title: 标题
            content: 内容

        返回:
            创建的 FAQ 对象
        """
        faq = FAQ(
            id=self._generate_id(group_id),
            group_id=group_id,
            target_qq=target_qq,
            start_time=start_time,
            end_time=end_time,
            created_at=datetime.now().isoformat(),
            title=title,
            content=content,
        )
        await self.save(faq)
        return faq

    async def get(self, group_id: int, faq_id: str) -> Optional[FAQ]:
        """获取指定 FAQ

        参数:
            group_id: 群号
            faq_id: FAQ ID

        返回:
            FAQ 对象，不存在则返回 None
        """
        group_dir = self._get_group_dir(group_id)
        file_path = group_dir / f"{faq_id}.json"

        from Undefined.utils import io

        data = await io.read_json(file_path, use_lock=False)
        if data:
            return FAQ.from_dict(data)
        return None

    async def list_all(self, group_id: int) -> list[FAQ]:
        """列出群组的所有 FAQ

        参数:
            group_id: 群号

        返回:
            FAQ 列表
        """
        group_dir = self._get_group_dir(group_id)
        faqs: list[FAQ] = []

        from Undefined.utils import io

        # 批量列出文件并读取
        for file_path in sorted(group_dir.glob("*.json"), reverse=True):
            try:
                data = await io.read_json(file_path, use_lock=False)
                if data:
                    faqs.append(FAQ.from_dict(data))
            except Exception as e:
                logger.error(f"读取 FAQ 失败 {file_path}: {e}")

        return faqs

    async def search(self, group_id: int, keyword: str) -> list[FAQ]:
        """搜索 FAQ

        根据关键词在标题和内容中搜索匹配的 FAQ

        参数:
            group_id: 群号
            keyword: 搜索关键词

        返回:
            匹配的 FAQ 列表
        """
        keyword_lower = keyword.lower()
        all_faqs = await self.list_all(group_id)

        matched: list[FAQ] = []
        for faq in all_faqs:
            # 在标题和内容中搜索
            if (
                keyword_lower in faq.title.lower()
                or keyword_lower in faq.content.lower()
            ):
                matched.append(faq)

        return matched

    async def delete(self, group_id: int, faq_id: str) -> bool:
        """删除 FAQ

        参数:
            group_id: 群号
            faq_id: FAQ ID

        返回:
            是否成功删除
        """
        group_dir = self._get_group_dir(group_id)
        file_path = group_dir / f"{faq_id}.json"

        from Undefined.utils import io

        return await io.delete_file(file_path)


def extract_faq_title(content: str) -> str:
    """从分析内容中提取 FAQ 标题

    参数:
        content: 分析内容

    返回:
        提取的标题
    """
    # 尝试从 FAQ 条目中提取问题
    for line in content.split("\n"):
        line = line.strip()
        if line.startswith("**问题**:") or line.startswith("**问题**："):
            title = line.split(":", 1)[-1].split("：", 1)[-1].strip()
            return title[:100]  # 限制长度

    # 尝试从 Bug 问题描述中提取
    in_bug_section = False
    for line in content.split("\n"):
        line = line.strip()
        if "Bug 问题描述" in line:
            in_bug_section = True
            continue
        if in_bug_section and line and not line.startswith("#"):
            return line[:100]

    return "未命名问题"
