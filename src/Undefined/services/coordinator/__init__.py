"""AI 协调器：组合群聊、私聊、合并与后台任务 mixin。"""

from __future__ import annotations


import logging
from pathlib import Path
from typing import Any

from Undefined.config import Config
from Undefined.services.coordinator.background import BackgroundMixin
from Undefined.services.coordinator.batching import BatchingMixin
from Undefined.services.coordinator.group import GroupReplyMixin
from Undefined.services.coordinator.private import PrivateReplyMixin
from Undefined.services.message_batcher import MessageBatcher
from Undefined.services.model_pool import ModelPoolService
from Undefined.services.queue_manager import QueueManager
from Undefined.services.security import SecurityService
from Undefined.utils.history import MessageHistoryManager
from Undefined.utils.scheduler import TaskScheduler
from Undefined.utils.sender import MessageSender

logger = logging.getLogger(__name__)


class AICoordinator(
    GroupReplyMixin,
    PrivateReplyMixin,
    BatchingMixin,
    BackgroundMixin,
):
    """AI 协调器，处理 AI 回复逻辑、Prompt 构建和队列管理"""

    def __init__(
        self,
        config: Config,
        ai: Any,  # AIClient
        queue_manager: QueueManager,
        history_manager: MessageHistoryManager,
        sender: MessageSender,
        onebot: Any,  # OneBotClient
        scheduler: TaskScheduler,
        security: SecurityService,
        command_dispatcher: Any = None,
    ) -> None:
        self.config = config
        self.ai = ai
        self.queue_manager = queue_manager
        self.history_manager = history_manager
        self.sender = sender
        self.onebot = onebot
        self.scheduler = scheduler
        self.security = security
        self.command_dispatcher = command_dispatcher
        self.model_pool = ModelPoolService(ai, config, sender)
        # batcher 由外部（handlers.py）创建并通过 set_batcher 注入；未注入时所有消息按单条流程直送。
        self._batcher: MessageBatcher | None = None

    def set_batcher(self, batcher: MessageBatcher | None) -> None:
        """注入消息合并器；传 None 等同于禁用合并。"""
        self._batcher = batcher

    @property
    def batcher(self) -> MessageBatcher | None:
        return self._batcher

    async def _send_image(self, tid: int, mtype: str, path: str) -> None:
        """发送图片或语音消息到群聊或私聊"""
        import os

        if not os.path.exists(path):
            return
        file_uri = Path(path).resolve().as_uri()
        ext = os.path.splitext(path)[1].lower()
        if ext in [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"]:
            msg = f"[CQ:image,file={file_uri}]"
        elif ext in [".mp3", ".wav", ".ogg", ".flac", ".m4a", ".aac"]:
            msg = f"[CQ:record,file={file_uri}]"
        else:
            return

        try:
            if mtype == "group":
                await self.sender.send_group_message(tid, msg, auto_history=False)
            elif mtype == "private":
                await self.sender.send_private_message(tid, msg, auto_history=False)
        except Exception:
            logger.exception("发送媒体文件失败")
