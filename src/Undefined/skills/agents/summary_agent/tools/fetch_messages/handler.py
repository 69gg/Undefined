from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from typing import Any

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


def _format_messages(messages: list[dict[str, Any]]) -> str:
    """Format messages into readable text for the summary agent."""
    lines = []
    for msg in messages:
        ts = msg.get("timestamp", "")
        name = msg.get("display_name", "未知用户")
        text = msg.get("message", "")
        role = msg.get("role", "")
        title = msg.get("title", "")

        prefix = f"[{ts}] "
        if title:
            prefix += f"[{title}] "
        if role and role not in ("member", ""):
            prefix += f"({role}) "
        prefix += f"{name}: "
        lines.append(f"{prefix}{text}")
    return "\n".join(lines)


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

    formatted = _format_messages(messages)
    total = len(messages)
    header = f"共获取 {total} 条消息"
    if time_range_str:
        header += f"(时间范围: {time_range_str})"
    return f"{header}\n\n{formatted}"
