"""最近消息获取工具（本地 history 优先）。"""

from __future__ import annotations

import logging
from typing import Any, cast

from Undefined.onebot import get_message_content, parse_message_time
from Undefined.utils.common import extract_text
from Undefined.utils.message_utils import fetch_group_messages

logger = logging.getLogger(__name__)


def _normalize_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _normalize_range(start: Any, end: Any) -> tuple[int, int]:
    """规范化最近消息区间参数。"""
    start_i = max(0, _normalize_int(start, 0))
    end_i = max(0, _normalize_int(end, 10))
    if end_i < start_i:
        return start_i, start_i
    return start_i, end_i


def _slice_recent(
    messages: list[dict[str, Any]], start: int, end: int
) -> list[dict[str, Any]]:
    """按 MessageHistoryManager.get_recent 的语义切片。"""
    total = len(messages)
    if total == 0:
        return []

    actual_start = total - end
    actual_end = total - start

    if actual_start < 0:
        actual_start = 0
    if actual_end > total:
        actual_end = total
    if actual_start >= actual_end:
        return []

    return messages[actual_start:actual_end]


def _format_group_history_message(
    raw_message: dict[str, Any],
    *,
    group_id: int,
    group_name_hint: str | None,
    bot_qq: int,
) -> dict[str, Any]:
    sender = raw_message.get("sender") or {}
    sender_id = str(sender.get("user_id") or "")
    sender_name = str(
        sender.get("card") or sender.get("nickname") or sender_id or "未知用户"
    )

    message_content = get_message_content(raw_message)
    text_content = extract_text(message_content, bot_qq)
    if not text_content:
        text_content = "(空消息)"

    timestamp = parse_message_time(raw_message).strftime("%Y-%m-%d %H:%M:%S")
    group_name = str(
        raw_message.get("group_name") or group_name_hint or f"群{group_id}"
    )

    return {
        "type": "group",
        "chat_id": str(group_id),
        "chat_name": group_name,
        "user_id": sender_id,
        "display_name": sender_name,
        "role": str(sender.get("role") or "member"),
        "title": str(sender.get("title") or ""),
        "timestamp": timestamp,
        "message": text_content,
    }


def _get_recent_from_history_manager(
    history_manager: Any,
    chat_id: str,
    msg_type: str,
    start: int,
    end: int,
) -> list[dict[str, Any]]:
    if history_manager is None:
        return []
    try:
        return cast(
            list[dict[str, Any]],
            history_manager.get_recent(chat_id, msg_type, start, end),
        )
    except Exception as exc:
        logger.warning("从本地 history 获取最近消息失败: %s", exc)
        return []


async def get_recent_messages_prefer_local(
    *,
    chat_id: str,
    msg_type: str,
    start: int,
    end: int,
    onebot_client: Any | None,
    history_manager: Any | None,
    bot_qq: int,
    group_name_hint: str | None = None,
    max_onebot_count: int = 5000,
) -> list[dict[str, Any]]:
    """优先从本地 history 获取最近消息，必要时回退到 OneBot。"""
    norm_start, norm_end = _normalize_range(start, end)
    if norm_end <= 0:
        return []

    local_messages = _get_recent_from_history_manager(
        history_manager,
        chat_id,
        msg_type,
        norm_start,
        norm_end,
    )
    if local_messages:
        return local_messages

    if msg_type == "group" and onebot_client is not None:
        try:
            group_id = int(chat_id)
            onebot_count = min(norm_end, max(1, int(max_onebot_count)))
            raw_messages = await fetch_group_messages(
                onebot_client,
                group_id,
                onebot_count,
                None,
            )

            if raw_messages:
                formatted_messages = [
                    _format_group_history_message(
                        message,
                        group_id=group_id,
                        group_name_hint=group_name_hint,
                        bot_qq=bot_qq,
                    )
                    for message in raw_messages
                ]
                formatted_messages.sort(key=lambda item: str(item.get("timestamp", "")))
                return _slice_recent(formatted_messages, norm_start, norm_end)
        except (TypeError, ValueError):
            logger.debug("群聊 chat_id 不是数字，无法回退到 OneBot: %s", chat_id)
        except Exception as exc:
            logger.warning("从 OneBot 获取群历史失败: %s", exc)

    return []


async def get_recent_messages_prefer_onebot(
    *,
    chat_id: str,
    msg_type: str,
    start: int,
    end: int,
    onebot_client: Any | None,
    history_manager: Any | None,
    bot_qq: int,
    group_name_hint: str | None = None,
    max_onebot_count: int = 5000,
) -> list[dict[str, Any]]:
    """兼容旧名称，当前行为等同于本地优先。"""
    return await get_recent_messages_prefer_local(
        chat_id=chat_id,
        msg_type=msg_type,
        start=start,
        end=end,
        onebot_client=onebot_client,
        history_manager=history_manager,
        bot_qq=bot_qq,
        group_name_hint=group_name_hint,
        max_onebot_count=max_onebot_count,
    )
