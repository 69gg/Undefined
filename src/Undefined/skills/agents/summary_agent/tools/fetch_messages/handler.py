from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from typing import Any

from Undefined.attachments import attachment_refs_to_xml
from Undefined.utils.xml import escape_xml_attr, escape_xml_text

logger = logging.getLogger(__name__)

_TIME_RANGE_PATTERN = re.compile(r"^(\d+)([hHdDwW])$")
_TIME_UNIT_SECONDS = {"h": 3600, "d": 86400, "w": 604800}
_MAX_COUNT = 500
_DEFAULT_COUNT = 50
_MAX_FETCH_FOR_TIME_FILTER = 2000


def _parse_time_range(value: str) -> int | None:
    """Parse time range string like '1h', '6h', '1d', '7d' into seconds."""
    match = _TIME_RANGE_PATTERN.match(value.strip())
    if not match:
        return None
    amount = int(match.group(1))
    unit = match.group(2).lower()
    return amount * _TIME_UNIT_SECONDS.get(unit, 3600)


def _filter_by_time(
    messages: list[dict[str, Any]], seconds: int
) -> list[dict[str, Any]]:
    """Filter messages to only include those within the given time range from now."""
    cutoff = datetime.now() - timedelta(seconds=seconds)
    result = []
    for msg in messages:
        ts_str = msg.get("timestamp", "")
        if not ts_str:
            continue
        try:
            ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
        if ts >= cutoff:
            result.append(msg)
    return result


def _format_message_location(msg_type_val: str, chat_name: str) -> str:
    if msg_type_val == "group":
        return chat_name if chat_name.endswith("群") else f"{chat_name}群"
    return "私聊"


def _normalize_messages_for_chat(
    messages: list[dict[str, Any]],
    *,
    chat_type: str,
    chat_id: str,
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for raw in messages:
        msg = dict(raw)
        if not str(msg.get("type", "") or "").strip():
            msg["type"] = chat_type
        if not str(msg.get("chat_id", "") or "").strip():
            msg["chat_id"] = chat_id
        if chat_type == "private" and not str(msg.get("chat_name", "") or "").strip():
            msg["chat_name"] = f"QQ用户{chat_id}"
        normalized.append(msg)
    return normalized


def _format_message_xml(msg: dict[str, Any]) -> str:
    msg_type_val = str(msg.get("type", "group") or "group")
    sender_name = str(msg.get("display_name", "未知用户") or "未知用户")
    sender_id = str(msg.get("user_id", "") or "")
    chat_id = str(msg.get("chat_id", "") or "")
    chat_name = str(msg.get("chat_name", "未知群聊") or "未知群聊")
    timestamp = str(msg.get("timestamp", "") or "")
    text = str(msg.get("message", "") or "")
    message_id = msg.get("message_id")
    role = str(msg.get("role", "member") or "member")
    title = str(msg.get("title", "") or "")
    level = str(msg.get("level", "") or "")
    attachments = msg.get("attachments", [])

    safe_sender = escape_xml_attr(sender_name)
    safe_sender_id = escape_xml_attr(sender_id)
    safe_chat_id = escape_xml_attr(chat_id)
    safe_chat_name = escape_xml_attr(chat_name)
    safe_role = escape_xml_attr(role)
    safe_title = escape_xml_attr(title)
    safe_time = escape_xml_attr(timestamp)
    safe_text = escape_xml_text(text)
    safe_location = escape_xml_attr(_format_message_location(msg_type_val, chat_name))

    msg_id_attr = ""
    if message_id is not None:
        msg_id_attr = f' message_id="{escape_xml_attr(str(message_id))}"'

    attachment_xml = (
        f"\n{attachment_refs_to_xml(attachments)}"
        if isinstance(attachments, list) and attachments
        else ""
    )

    if msg_type_val == "group":
        level_attr = f' level="{escape_xml_attr(level)}"' if level else ""
        return (
            f'<message{msg_id_attr} sender="{safe_sender}" sender_id="{safe_sender_id}" '
            f'group_id="{safe_chat_id}" group_name="{safe_chat_name}" location="{safe_location}" '
            f'role="{safe_role}" title="{safe_title}"{level_attr} time="{safe_time}">\n'
            f"<content>{safe_text}</content>{attachment_xml}\n"
            f"</message>"
        )

    return (
        f'<message{msg_id_attr} sender="{safe_sender}" sender_id="{safe_sender_id}" '
        f'location="{safe_location}" time="{safe_time}">\n'
        f"<content>{safe_text}</content>{attachment_xml}\n"
        f"</message>"
    )


def _format_messages(messages: list[dict[str, Any]]) -> str:
    """Format messages into main-AI-compatible XML for the summary agent."""
    return "\n---\n".join(_format_message_xml(msg) for msg in messages)


async def execute(args: dict[str, Any], context: dict[str, Any]) -> str:
    """拉取当前会话的聊天消息。"""
    history_manager = context.get("history_manager")
    if not history_manager:
        return "历史记录管理器未配置"

    group_id = context.get("group_id", 0) or 0
    user_id = context.get("user_id", 0) or 0

    if int(group_id) > 0:
        chat_type = "group"
        chat_id = str(group_id)
    else:
        chat_type = "private"
        chat_id = str(user_id)

    time_range_str = str(args.get("time_range", "")).strip()
    raw_count = args.get("count", _DEFAULT_COUNT)
    try:
        count = min(max(int(raw_count), 1), _MAX_COUNT)
    except (TypeError, ValueError):
        count = _DEFAULT_COUNT

    if time_range_str:
        seconds = _parse_time_range(time_range_str)
        if seconds is None:
            return f"无法解析时间范围: {time_range_str}(支持格式: 1h, 6h, 1d, 7d)"
        fetch_count = max(count * 2, _MAX_FETCH_FOR_TIME_FILTER)
        messages = history_manager.get_recent(chat_id, chat_type, 0, fetch_count)
        if messages:
            messages = _filter_by_time(messages, seconds)
    else:
        messages = history_manager.get_recent(chat_id, chat_type, 0, count)

    if not messages:
        return "当前会话暂无消息记录"

    messages = _normalize_messages_for_chat(
        messages, chat_type=chat_type, chat_id=chat_id
    )

    formatted = _format_messages(messages)
    total = len(messages)
    header = f"共获取 {total} 条消息"
    if time_range_str:
        header += f"(时间范围: {time_range_str})"
    return f"{header}\n\n{formatted}"
