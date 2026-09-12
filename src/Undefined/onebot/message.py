"""OneBot 消息解析辅助函数。"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


def parse_message_time(message: dict[str, Any]) -> datetime:
    """解析消息时间。

    兼容秒级/毫秒级时间戳与字符串输入，异常时回退到当前时间。
    """

    return try_parse_message_time(message) or datetime.now()


def try_parse_message_time(message: dict[str, Any]) -> datetime | None:
    """解析秒级、毫秒级或数值字符串时间戳，无效时返回 None。

    用于必须保留时间有效性的历史统计，不以当前时间补全缺失记录。
    """

    raw_timestamp = message.get("time")

    if raw_timestamp is None or isinstance(raw_timestamp, bool):
        return None

    try:
        timestamp = float(raw_timestamp)
    except (TypeError, ValueError, OverflowError):
        logger.debug("[OneBot] 无法解析消息时间戳: %s", raw_timestamp)
        return None

    # 13 位毫秒时间戳自动降为秒。
    if timestamp > 1_000_000_000_000:
        timestamp /= 1000.0

    if timestamp <= 0:
        return None

    try:
        return datetime.fromtimestamp(timestamp)
    except (OSError, OverflowError, ValueError):
        logger.debug("[OneBot] 时间戳越界或非法: %s", raw_timestamp)
        return None


def get_message_sender_id(message: dict[str, Any]) -> int:
    """获取消息发送者 QQ 号"""
    sender: dict[str, Any] = message.get("sender", {})
    user_id: int = sender.get("user_id", 0)
    return user_id


def get_message_content(message: dict[str, Any]) -> list[dict[str, Any]]:
    """获取消息内容（CQ 码数组格式）"""
    msg = message.get("message", [])
    if isinstance(msg, str):
        # 如果是字符串格式，转换为数组格式
        return [{"type": "text", "data": {"text": msg}}]
    content: list[dict[str, Any]] = msg
    return content
