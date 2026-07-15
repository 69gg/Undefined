from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)
_WECHAT_MESSAGE_ID_RE = re.compile(r"^\S+$")


def mark_message_sent(context: dict[str, Any]) -> None:
    marker = context.get("mark_message_sent_this_turn")
    if not callable(marker):
        logger.warning("缺少 mark_message_sent_this_turn 上下文依赖")
        return
    marker(context)


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
