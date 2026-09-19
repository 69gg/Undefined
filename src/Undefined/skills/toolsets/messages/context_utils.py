from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)
_WECHAT_MESSAGE_ID_RE = re.compile(r"^\S+$")
DELIVERY_UNCERTAIN_RESULT = (
    "投递状态：结果未确认（上游在发送阶段超时，消息可能已经送达）。"
    "当前调用按已投递处理，禁止自动重试；只有用户明确要求重发时才能再次发送。"
)


def mark_message_sent(context: dict[str, Any]) -> None:
    marker = context.get("mark_message_sent_this_turn")
    if not callable(marker):
        logger.warning("缺少 mark_message_sent_this_turn 上下文依赖")
        return
    marker(context)


def is_delivery_uncertain_error(error: BaseException) -> bool:
    """Return whether a transport error represents an ambiguous delivery."""

    return bool(getattr(error, "delivery_uncertain", False))


def file_transfer_error_message(error: BaseException) -> str | None:
    """通过公共错误属性读取可展示说明，技能无需导入运行时传输模块。"""
    if not getattr(error, "file_transfer_error", False):
        return None
    return str(getattr(error, "user_message", str(error)))


def file_transfer_error_dispatched_count(error: BaseException) -> int:
    """读取传输错误携带的已成功派发附件数量，未携带时为 0。"""
    count = getattr(error, "dispatched_file_count", 0)
    return count if isinstance(count, int) and count > 0 else 0


def handle_delivery_uncertain(context: dict[str, Any]) -> str:
    """Mark an ambiguous attempt as sent and return non-retry tool feedback."""

    mark_message_sent(context)
    return DELIVERY_UNCERTAIN_RESULT


def parse_reply_to(
    value: Any,
    *,
    channel: str,
) -> tuple[int | str | None, str | None]:
    """Validate a channel-specific reply target without losing string IDs."""

    if value is None:
        return None, None
    if isinstance(value, bool):
        return None, "reply_to 必须是有效消息 ID"
    if channel != "wechat":
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return None, "reply_to 必须是正整数"
        return (parsed, None) if parsed > 0 else (None, "reply_to 必须是正整数")
    if isinstance(value, int):
        return (value, None) if value > 0 else (None, "reply_to 必须是有效消息 ID")
    text = str(value).strip()
    if not _WECHAT_MESSAGE_ID_RE.fullmatch(text):
        return None, "reply_to 必须是当前微信会话中的有效消息 ID"
    return text, None


def normalize_sent_message_id(value: Any) -> str | None:
    """Return a safe transport-visible message ID for tool feedback."""

    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return str(value) if value > 0 else None
    text = str(value).strip()
    return text if _WECHAT_MESSAGE_ID_RE.fullmatch(text) else None
