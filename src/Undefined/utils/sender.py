"""消息发送管理"""

import logging
from pathlib import Path

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


def _extract_message_id(result: object) -> int | None:
    if not isinstance(result, dict):
        return None

    message_id = result.get("message_id")
    if message_id is None:
        data = result.get("data")
        if isinstance(data, dict):
            message_id = data.get("message_id")

    try:
        return int(message_id) if message_id is not None else None
    except (TypeError, ValueError):
        return None


def _format_size(size_bytes: int | None) -> str:
    if size_bytes is None or size_bytes < 0:
        return "未知大小"
    if size_bytes < 1024:
        return f"{size_bytes}B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f}KB"
    if size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / 1024 / 1024:.2f}MB"
    return f"{size_bytes / 1024 / 1024 / 1024:.2f}GB"


def _build_file_history_message(file_name: str, size_bytes: int | None) -> str:
    return f"[文件] {file_name} ({_format_size(size_bytes)})"


def _get_file_size(file_path: str) -> int | None:
    try:
        return Path(file_path).stat().st_size
    except OSError:
        return None


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
        *,
        mark_sent: bool = True,
        reply_to: int | None = None,
    ) -> None:
        """发送群消息"""
        if not self.config.is_group_allowed(group_id):
            enabled = self.config.access_control_enabled()
            reason = self.config.group_access_denied_reason(group_id) or "unknown"
            logger.warning(
                "[访问控制] 已拦截群消息发送: group=%s reason=%s (access enabled=%s)",
                group_id,
                reason,
                enabled,
            )
            raise PermissionError(
                "blocked by access control: "
                f"type=group reason={reason} group_id={int(group_id)} enabled={enabled}"
            )

        safe_message = redact_string(message)
        logger.info(f"[发送消息] 目标群:{group_id} | 内容摘要:{safe_message[:100]}...")

        # 将 [@{qq_id}] 格式转换为 [CQ:at,qq={qq_id}]
        message = process_at_mentions(message)

        # 准备历史记录文本（不含 reply 段）
        history_content: str | None = None
        if auto_history:
            hist_segments = message_to_segments(message)
            history_content = extract_text(hist_segments, self.bot_qq)
            if history_prefix:
                history_content = f"{history_prefix}{history_content}"

        # 发送消息
        bot_message_id: int | None = None
        if len(message) <= MAX_MESSAGE_LENGTH:
            segments = message_to_segments(message)
            if reply_to is not None:
                segments.insert(0, {"type": "reply", "data": {"id": str(reply_to)}})
            result = await self.onebot.send_group_message(
                group_id, segments, mark_sent=mark_sent
            )
            bot_message_id = _extract_message_id(result)
        else:
            bot_message_id = await self._send_chunked_group(
                group_id, message, mark_sent=mark_sent, reply_to=reply_to
            )

        # 发送成功后写入历史记录
        if auto_history and history_content is not None:
            logger.debug(f"[历史记录] 正在保存 Bot 群聊回复: group={group_id}")
            await self.history_manager.add_group_message(
                group_id=group_id,
                sender_id=self.bot_qq,
                text_content=history_content,
                sender_nickname="Bot",
                group_name="",
                message_id=bot_message_id,
            )

    async def _send_chunked_group(
        self,
        group_id: int,
        message: str,
        *,
        mark_sent: bool = True,
        reply_to: int | None = None,
    ) -> int | None:
        """分段发送群消息，返回第一段的 message_id。"""
        logger.info(f"[消息分段] 消息过长 ({len(message)} 字符)，正在自动分段发送...")
        lines = message.split("\n")
        current_chunk: list[str] = []
        current_length = 0
        chunk_count = 0
        first_message_id: int | None = None

        for line in lines:
            line_length = len(line) + 1

            if current_length + line_length > MAX_MESSAGE_LENGTH and current_chunk:
                chunk_count += 1
                chunk_text = "\n".join(current_chunk)
                logger.debug(f"[消息分段] 发送第 {chunk_count} 段")
                segments = message_to_segments(chunk_text)
                if chunk_count == 1 and reply_to is not None:
                    segments.insert(0, {"type": "reply", "data": {"id": str(reply_to)}})
                result = await self.onebot.send_group_message(
                    group_id, segments, mark_sent=mark_sent
                )
                if chunk_count == 1:
                    first_message_id = _extract_message_id(result)
                current_chunk = []
                current_length = 0

            current_chunk.append(line)
            current_length += line_length

        if current_chunk:
            chunk_count += 1
            chunk_text = "\n".join(current_chunk)
            logger.debug(f"[消息分段] 发送第 {chunk_count} 段 (最后一段)")
            segments = message_to_segments(chunk_text)
            if chunk_count == 1 and reply_to is not None:
                segments.insert(0, {"type": "reply", "data": {"id": str(reply_to)}})
            result = await self.onebot.send_group_message(
                group_id, segments, mark_sent=mark_sent
            )
            if chunk_count == 1:
                first_message_id = _extract_message_id(result)

        logger.info(f"[消息分段] 已完成 {chunk_count} 段消息的发送")
        return first_message_id

    async def send_private_message(
        self,
        user_id: int,
        message: str,
        auto_history: bool = True,
        *,
        mark_sent: bool = True,
        reply_to: int | None = None,
    ) -> None:
        """发送私聊消息"""
        if not self.config.is_private_allowed(user_id):
            enabled = self.config.access_control_enabled()
            reason = self.config.private_access_denied_reason(user_id) or "unknown"
            logger.warning(
                "[访问控制] 已拦截私聊消息发送: user=%s reason=%s (access enabled=%s)",
                user_id,
                reason,
                enabled,
            )
            raise PermissionError(
                "blocked by access control: "
                f"type=private reason={reason} user_id={int(user_id)} enabled={enabled}"
            )

        safe_message = redact_string(message)
        logger.info(f"[发送消息] 目标用户:{user_id} | 内容摘要:{safe_message[:100]}...")

        # 准备历史记录文本
        history_content: str | None = None
        if auto_history:
            hist_segments = message_to_segments(message)
            history_content = extract_text(hist_segments, self.bot_qq)

        # 发送消息
        bot_message_id: int | None = None
        if len(message) <= MAX_MESSAGE_LENGTH:
            segments = message_to_segments(message)
            if reply_to is not None:
                segments.insert(0, {"type": "reply", "data": {"id": str(reply_to)}})
            result = await self.onebot.send_private_message(
                user_id, segments, mark_sent=mark_sent
            )
            bot_message_id = _extract_message_id(result)
        else:
            bot_message_id = await self._send_chunked_private(
                user_id, message, mark_sent=mark_sent, reply_to=reply_to
            )

        # 发送成功后写入历史记录
        if auto_history and history_content is not None:
            logger.debug(f"[历史记录] 正在保存 Bot 私聊回复: user={user_id}")
            await self.history_manager.add_private_message(
                user_id=user_id,
                text_content=history_content,
                display_name="Bot",
                user_name="Bot",
                message_id=bot_message_id,
            )

    async def _send_chunked_private(
        self,
        user_id: int,
        message: str,
        *,
        mark_sent: bool = True,
        reply_to: int | None = None,
    ) -> int | None:
        """分段发送私聊消息，返回第一段的 message_id。"""
        logger.info(f"[消息分段] 消息过长 ({len(message)} 字符)，正在自动分段发送...")
        lines = message.split("\n")
        current_chunk: list[str] = []
        current_length = 0
        chunk_count = 0
        first_message_id: int | None = None

        for line in lines:
            line_length = len(line) + 1

            if current_length + line_length > MAX_MESSAGE_LENGTH and current_chunk:
                chunk_count += 1
                chunk_text = "\n".join(current_chunk)
                logger.debug(f"[消息分段] 发送第 {chunk_count} 段")
                segments = message_to_segments(chunk_text)
                if chunk_count == 1 and reply_to is not None:
                    segments.insert(0, {"type": "reply", "data": {"id": str(reply_to)}})
                result = await self.onebot.send_private_message(
                    user_id, segments, mark_sent=mark_sent
                )
                if chunk_count == 1:
                    first_message_id = _extract_message_id(result)
                current_chunk = []
                current_length = 0

            current_chunk.append(line)
            current_length += line_length

        if current_chunk:
            chunk_count += 1
            chunk_text = "\n".join(current_chunk)
            logger.debug(f"[消息分段] 发送第 {chunk_count} 段 (最后一段)")
            segments = message_to_segments(chunk_text)
            if chunk_count == 1 and reply_to is not None:
                segments.insert(0, {"type": "reply", "data": {"id": str(reply_to)}})
            result = await self.onebot.send_private_message(
                user_id, segments, mark_sent=mark_sent
            )
            if chunk_count == 1:
                first_message_id = _extract_message_id(result)

        logger.info(f"[消息分段] 已完成 {chunk_count} 段消息的发送")
        return first_message_id

    async def send_group_poke(
        self,
        group_id: int,
        user_id: int,
        *,
        mark_sent: bool = True,
    ) -> None:
        """在群聊中拍一拍指定成员。"""
        if not self.config.is_group_allowed(group_id):
            enabled = self.config.access_control_enabled()
            reason = self.config.group_access_denied_reason(group_id) or "unknown"
            logger.warning(
                "[访问控制] 已拦截群拍一拍: group=%s user=%s reason=%s (access enabled=%s)",
                group_id,
                user_id,
                reason,
                enabled,
            )
            raise PermissionError(
                "blocked by access control: "
                f"type=group reason={reason} group_id={int(group_id)} enabled={enabled}"
            )

        logger.info("[拍一拍] 群=%s 用户=%s", group_id, user_id)
        await self.onebot.send_group_poke(group_id, user_id, mark_sent=mark_sent)

    async def send_private_poke(
        self,
        user_id: int,
        *,
        mark_sent: bool = True,
    ) -> None:
        """在私聊中拍一拍指定用户。"""
        if not self.config.is_private_allowed(user_id):
            enabled = self.config.access_control_enabled()
            reason = self.config.private_access_denied_reason(user_id) or "unknown"
            logger.warning(
                "[访问控制] 已拦截私聊拍一拍: user=%s reason=%s (access enabled=%s)",
                user_id,
                reason,
                enabled,
            )
            raise PermissionError(
                "blocked by access control: "
                f"type=private reason={reason} user_id={int(user_id)} enabled={enabled}"
            )

        logger.info("[拍一拍] 私聊用户=%s", user_id)
        await self.onebot.send_private_poke(user_id, mark_sent=mark_sent)

    async def send_group_file(
        self,
        group_id: int,
        file_path: str,
        name: str | None = None,
        auto_history: bool = True,
    ) -> None:
        """通过统一发送层上传群文件。"""
        if not self.config.is_group_allowed(group_id):
            enabled = self.config.access_control_enabled()
            reason = self.config.group_access_denied_reason(group_id) or "unknown"
            logger.warning(
                "[访问控制] 已拦截群文件发送: group=%s reason=%s (access enabled=%s)",
                group_id,
                reason,
                enabled,
            )
            raise PermissionError(
                "blocked by access control: "
                f"type=group reason={reason} group_id={int(group_id)} enabled={enabled}"
            )

        file_name = name or Path(file_path).name
        logger.info("[发送文件] 目标群:%s | 文件:%s", group_id, file_name)

        await self.onebot.upload_group_file(group_id, file_path, file_name)

        if not auto_history:
            return

        file_size = _get_file_size(file_path)
        history_content = _build_file_history_message(file_name, file_size)
        try:
            await self.history_manager.add_group_message(
                group_id=group_id,
                sender_id=self.bot_qq,
                text_content=history_content,
                sender_nickname="Bot",
                group_name="",
            )
        except Exception:
            logger.exception(
                "[历史记录] 记录群文件发送失败: group=%s file=%s",
                group_id,
                file_name,
            )

    async def send_private_file(
        self,
        user_id: int,
        file_path: str,
        name: str | None = None,
        auto_history: bool = True,
    ) -> None:
        """通过统一发送层上传私聊文件。"""
        if not self.config.is_private_allowed(user_id):
            enabled = self.config.access_control_enabled()
            reason = self.config.private_access_denied_reason(user_id) or "unknown"
            logger.warning(
                "[访问控制] 已拦截私聊文件发送: user=%s reason=%s (access enabled=%s)",
                user_id,
                reason,
                enabled,
            )
            raise PermissionError(
                "blocked by access control: "
                f"type=private reason={reason} user_id={int(user_id)} enabled={enabled}"
            )

        file_name = name or Path(file_path).name
        logger.info("[发送文件] 目标用户:%s | 文件:%s", user_id, file_name)

        await self.onebot.upload_private_file(user_id, file_path, file_name)

        if not auto_history:
            return

        file_size = _get_file_size(file_path)
        history_content = _build_file_history_message(file_name, file_size)
        try:
            await self.history_manager.add_private_message(
                user_id=user_id,
                text_content=history_content,
                display_name="Bot",
                user_name="Bot",
            )
        except Exception:
            logger.exception(
                "[历史记录] 记录私聊文件发送失败: user=%s file=%s",
                user_id,
                file_name,
            )
