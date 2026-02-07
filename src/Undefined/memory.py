"""AI 记忆存储管理模块"""

import json
import logging
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# 记忆数据存储路径
MEMORY_FILE_PATH = Path("data/memory.json")


@dataclass
class Memory:
    """单条记忆数据"""

    uuid: str  # 唯一标识符
    fact: str  # 记忆内容
    created_at: str  # 创建时间


class MemoryStorage:
    """AI 记忆存储管理器"""

    def __init__(self, max_memories: int = 500) -> None:
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

            needs_rewrite = False
            loaded_memories = []
            for item in data:
                # 检查是否存在 uuid，如果不存在则自动生成
                if "uuid" not in item:
                    item["uuid"] = str(uuid.uuid4())
                    needs_rewrite = True
                loaded_memories.append(Memory(**item))

            self._memories = loaded_memories
            logger.info(
                "[记忆] 加载完成: count=%s file=%s",
                len(self._memories),
                MEMORY_FILE_PATH,
            )

            # 如果检测到旧格式，自动分配 UUID，将在后续保存时应用到文件
            if needs_rewrite:
                logger.info("[记忆] 检测到旧格式记录，已在内存中自动分配 UUID")

        except Exception as exc:
            logger.warning("[记忆] 加载失败: %s", exc)
            self._memories = []

    async def _save(self) -> None:
        """保存记忆到文件"""
        try:
            from Undefined.utils import io

            data = [asdict(m) for m in self._memories]
            await io.write_json(MEMORY_FILE_PATH, data, use_lock=True)
            logger.debug("[记忆] 保存完成: count=%s", len(self._memories))
        except Exception as exc:
            logger.error("[记忆] 保存失败: %s", exc)

    async def add(self, fact: str) -> Optional[str]:
        """添加一条记忆

        参数:
            fact: 记忆内容

        返回:
            新生成的 UUID，如果失败则返回 None
        """
        if not fact or not fact.strip():
            logger.warning("[记忆] 尝试添加空记忆，已忽略")
            return None

        # 检查是否已存在相同内容
        for existing in self._memories:
            if existing.fact == fact.strip():
                logger.debug("[记忆] 记忆内容已存在，忽略: %s...", fact[:50])
                return existing.uuid

        memory = Memory(
            uuid=str(uuid.uuid4()),
            fact=fact.strip(),
            created_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )

        # 添加到列表末尾
        self._memories.append(memory)

        # 如果超过上限，移除最旧的
        if len(self._memories) > self.max_memories:
            removed = self._memories.pop(0)
            logger.info(
                "[记忆] 超过上限，移除最旧记忆: %s...",
                removed.fact[:50],
            )

        await self._save()
        logger.info(
            "[记忆] 已添加: uuid=%s size=%s/%s content=%s...",
            memory.uuid,
            len(self._memories),
            self.max_memories,
            fact[:50],
        )
        return memory.uuid

    async def update(self, memory_uuid: str, fact: str) -> bool:
        """更新一条记忆

        参数:
            memory_uuid: 记忆的 UUID
            fact: 新的消息内容

        返回:
            是否更新成功
        """
        for i, m in enumerate(self._memories):
            if m.uuid == memory_uuid:
                self._memories[i].fact = fact.strip()
                await self._save()
                logger.info(
                    "[记忆] 已更新: uuid=%s content=%s...",
                    memory_uuid,
                    fact[:50],
                )
                return True
        logger.warning("[记忆] 未找到 UUID=%s 的记忆，更新失败", memory_uuid)
        return False

    async def delete(self, memory_uuid: str) -> bool:
        """删除一条记忆

        参数:
            memory_uuid: 记忆的 UUID

        返回:
            是否删除成功
        """
        for i, m in enumerate(self._memories):
            if m.uuid == memory_uuid:
                removed = self._memories.pop(i)
                await self._save()
                logger.info(
                    "[记忆] 已删除: uuid=%s content=%s...",
                    memory_uuid,
                    removed.fact[:50],
                )
                return True
        logger.warning("[记忆] 未找到 UUID=%s 的记忆，删除失败", memory_uuid)
        return False

    def get_all(self) -> list[Memory]:
        """获取所有记忆

        返回:
            记忆列表（按时间顺序，最早的在前）
        """
        return self._memories.copy()

    async def clear(self) -> None:
        """清空所有记忆"""
        self._memories = []
        await self._save()
        logger.info("[记忆] 已清空所有记忆")

    def count(self) -> int:
        """获取记忆数量

        返回:
            当前记忆数量
        """
        return len(self._memories)
