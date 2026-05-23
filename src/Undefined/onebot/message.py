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

    raw_timestamp = message.get("time")

    if raw_timestamp is None:
        return datetime.now()

    try:
        timestamp = float(raw_timestamp)
    except (TypeError, ValueError):
        logger.debug("[OneBot] 无法解析消息时间戳，使用当前时间: %s", raw_timestamp)
        return datetime.now()

    # 13 位毫秒时间戳自动降为秒。
    if timestamp > 1_000_000_000_000:
        timestamp /= 1000.0

    if timestamp <= 0:
        return datetime.now()

    try:
        return datetime.fromtimestamp(timestamp)
    except (OSError, OverflowError, ValueError):
        # 越界或非法 epoch 回退当前时间，避免整条消息解析失败。
        logger.debug("[OneBot] 时间戳越界，使用当前时间: %s", raw_timestamp)
        return datetime.now()


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
