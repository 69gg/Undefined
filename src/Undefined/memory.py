"""AI 记忆存储管理模块"""

import json
import logging
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# 记忆数据存储路径
MEMORY_FILE_PATH = Path("data/memory.json")


@dataclass
class Memory:
    """单条记忆数据"""

    fact: str  # 记忆内容
    created_at: str  # 创建时间


class MemoryStorage:
    """AI 记忆存储管理器"""

    def __init__(self, max_memories: int = 100) -> None:
        """初始化记忆存储

        参数:
            max_memories: 最大记忆数量
        """
        self.max_memories = max_memories
        self._memories: list[Memory] = []
        self._load()

    def _load(self) -> None:
        """从文件加载记忆"""
        if not MEMORY_FILE_PATH.exists():
            self._memories = []
            return

        try:
            with open(MEMORY_FILE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._memories = [Memory(**item) for item in data]
            logger.info(f"已加载 {len(self._memories)} 条记忆")
        except Exception as e:
            logger.warning(f"加载记忆失败: {e}")
            self._memories = []

    def _save(self) -> None:
        """保存记忆到文件"""
        try:
            MEMORY_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(MEMORY_FILE_PATH, "w", encoding="utf-8") as f:
                json.dump(
                    [asdict(m) for m in self._memories], f, ensure_ascii=False, indent=2
                )
            logger.debug(f"已保存 {len(self._memories)} 条记忆")
        except Exception as e:
            logger.error(f"保存记忆失败: {e}")

    def add(self, fact: str) -> bool:
        """添加一条记忆

        参数:
            fact: 记忆内容

        返回:
            是否添加成功
        """
        if not fact or not fact.strip():
            logger.warning("尝试添加空记忆，已忽略")
            return False

        # 检查是否已存在相同记忆
        for existing in self._memories:
            if existing.fact == fact.strip():
                logger.debug(f"记忆已存在，忽略: {fact[:50]}...")
                return False

        memory = Memory(
            fact=fact.strip(), created_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        )

        # 添加到列表末尾
        self._memories.append(memory)

        # 如果超过上限，移除最旧的（最早的）
        if len(self._memories) > self.max_memories:
            removed = self._memories.pop(0)
            logger.info(f"记忆数量超过上限，移除最旧记忆: {removed.fact[:50]}...")

        self._save()
        logger.info(
            f"已添加记忆: {fact[:50]}... (当前 {len(self._memories)}/{self.max_memories})"
        )
        return True

    def get_all(self) -> list[Memory]:
        """获取所有记忆

        返回:
            记忆列表（按时间顺序，最早的在前）
        """
        return self._memories.copy()

    def clear(self) -> None:
        """清空所有记忆"""
        self._memories = []
        self._save()
        logger.info("已清空所有记忆")

    def count(self) -> int:
        """获取记忆数量

        返回:
            当前记忆数量
        """
        return len(self._memories)
