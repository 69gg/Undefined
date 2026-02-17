"""消息发送管理"""

import logging

from Undefined.config import Config
from Undefined.onebot import OneBotClient
from Undefined.utils.history import MessageHistoryManager
from Undefined.utils.common import (
    message_to_segments,
    extract_text,
    process_at_mentions,
)
from Undefined.utils.logging import redact_string

logger = logging.getLogger(__name__)

# QQ 消息长度限制（保守估算）
MAX_MESSAGE_LENGTH = 4000


class MessageSender:
    """消息发送器"""

    def __init__(
        self,
        onebot: OneBotClient,
        history_manager: MessageHistoryManager,
        bot_qq: int,
        config: Config,
    ):
        self.onebot = onebot
        self.history_manager = history_manager
        self.bot_qq = bot_qq
        self.config = config

    async def send_group_message(
        self,
        group_id: int,
        message: str,
        auto_history: bool = True,
        history_prefix: str = "",
    ) -> None:
        """发送群消息"""
        if not self.config.is_group_allowed(group_id):
            enabled = self.config.access_control_enabled()
            logger.warning(
                "[访问控制] 已拦截群消息发送: group=%s (allowlist enabled=%s)",
                group_id,
                enabled,
            )
            raise PermissionError(
                f"blocked by allowlist: group_id={int(group_id)} enabled={enabled}"
            )

        safe_message = redact_string(message)
        logger.info(f"[发送消息] 目标群:{group_id} | 内容摘要:{safe_message[:100]}...")

        # 将 [@{qq_id}] 格式转换为 [CQ:at,qq={qq_id}]
        message = process_at_mentions(message)

        # 保存到历史记录
        if auto_history:
            # 解析消息以便正确处理 CQ 码（如图片）
            segments = message_to_segments(message)
            history_content = extract_text(segments, self.bot_qq)
            if history_prefix:
                history_content = f"{history_prefix}{history_content}"
            logger.debug(f"[历史记录] 正在保存 Bot 群聊回复: group={group_id}")

            await self.history_manager.add_group_message(
                group_id=group_id,
                sender_id=self.bot_qq,
                text_content=history_content,
                sender_nickname="Bot",
                group_name="",  # 群名暂时未知，通常不需要Bot去获取
            )

        # 自动分段发送
        if len(message) <= MAX_MESSAGE_LENGTH:
            segments = message_to_segments(message)
            await self.onebot.send_group_message(group_id, segments)
            return

        # 按行分割
        logger.info(f"[消息分段] 消息过长 ({len(message)} 字符)，正在自动分段发送...")
        lines = message.split("\n")
        current_chunk: list[str] = []
        current_length = 0
        chunk_count = 0

        for line in lines:
            line_length = len(line) + 1

            if current_length + line_length > MAX_MESSAGE_LENGTH and current_chunk:
                chunk_count += 1
                chunk_text = "\n".join(current_chunk)
                logger.debug(f"[消息分段] 发送第 {chunk_count} 段")
                await self.onebot.send_group_message(
                    group_id, message_to_segments(chunk_text)
                )
                current_chunk = []
                current_length = 0

            current_chunk.append(line)
            current_length += line_length

        if current_chunk:
            chunk_count += 1
            chunk_text = "\n".join(current_chunk)
            logger.debug(f"[消息分段] 发送第 {chunk_count} 段 (最后一段)")
            await self.onebot.send_group_message(
                group_id, message_to_segments(chunk_text)
            )

        logger.info(f"[消息分段] 已完成 {chunk_count} 段消息的发送")

    async def send_private_message(
        self, user_id: int, message: str, auto_history: bool = True
    ) -> None:
        """发送私聊消息"""
        if not self.config.is_private_allowed(user_id):
            enabled = self.config.access_control_enabled()
            logger.warning(
                "[访问控制] 已拦截私聊消息发送: user=%s (allowlist enabled=%s)",
                user_id,
                enabled,
            )
            raise PermissionError(
                f"blocked by allowlist: user_id={int(user_id)} enabled={enabled}"
            )

        safe_message = redact_string(message)
        logger.info(f"[发送消息] 目标用户:{user_id} | 内容摘要:{safe_message[:100]}...")
        # 保存到历史记录
        if auto_history:
            # 解析消息以便正确处理 CQ 码
            segments = message_to_segments(message)
            history_content = extract_text(segments, self.bot_qq)
            logger.debug(f"[历史记录] 正在保存 Bot 私聊回复: user={user_id}")

            await self.history_manager.add_private_message(
                user_id=user_id,
                text_content=history_content,
                display_name="Bot",
                user_name="Bot",
            )

        # 自动分段发送
        if len(message) <= MAX_MESSAGE_LENGTH:
            segments = message_to_segments(message)
            await self.onebot.send_private_message(user_id, segments)
            return

        # 按行分割
        logger.info(f"[消息分段] 消息过长 ({len(message)} 字符)，正在自动分段发送...")
        lines = message.split("\n")
        current_chunk: list[str] = []
        current_length = 0
        chunk_count = 0

        for line in lines:
            line_length = len(line) + 1

            if current_length + line_length > MAX_MESSAGE_LENGTH and current_chunk:
                chunk_count += 1
                chunk_text = "\n".join(current_chunk)
                logger.debug(f"[消息分段] 发送第 {chunk_count} 段")
                await self.onebot.send_private_message(
                    user_id, message_to_segments(chunk_text)
                )
                current_chunk = []
                current_length = 0

            current_chunk.append(line)
            current_length += line_length

        if current_chunk:
            chunk_count += 1
            chunk_text = "\n".join(current_chunk)
            logger.debug(f"[消息分段] 发送第 {chunk_count} 段 (最后一段)")
            await self.onebot.send_private_message(
                user_id, message_to_segments(chunk_text)
            )

        logger.info(f"[消息分段] 已完成 {chunk_count} 段消息的发送")
