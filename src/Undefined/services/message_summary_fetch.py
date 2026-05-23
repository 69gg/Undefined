"""Shared helpers for fetching chat messages for summary flows."""

from __future__ import annotations

import asyncio
import re
from datetime import datetime, timedelta
from typing import Any

from Undefined.utils.xml import format_messages_xml

_TIME_RANGE_PATTERN = re.compile(r"^(\d+)([hHdDwW])$")
_TIME_UNIT_SECONDS = {"h": 3600, "d": 86400, "w": 604800}
_DEFAULT_COUNT = 50

_FALLBACK_MAX_COUNT = 1000
_FALLBACK_MAX_FETCH_FOR_TIME_FILTER = 5000


def _get_history_limit(runtime_config: Any, key: str, fallback: int) -> int:
    if runtime_config is not None:
        val = getattr(runtime_config, key, None)
        if isinstance(val, int) and val > 0:
            return val
    return fallback


def parse_time_range(value: str) -> int | None:
    """Parse time range string like '1h', '6h', '1d', '7d' into seconds."""
    match = _TIME_RANGE_PATTERN.match(value.strip())
    if not match:
        return None
    amount = int(match.group(1))
    unit = match.group(2).lower()
    return amount * _TIME_UNIT_SECONDS.get(unit, 3600)


def filter_by_time(
    messages: list[dict[str, Any]], seconds: int
) -> list[dict[str, Any]]:
    """Filter messages to only include those within the given time range from now."""
    cutoff = datetime.now() - timedelta(seconds=seconds)
    result: list[dict[str, Any]] = []
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


def normalize_messages_for_chat(
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


async def fetch_session_messages(
    history_manager: Any,
    *,
    group_id: int,
    user_id: int,
    count: int | None = None,
    time_range: str | None = None,
    runtime_config: Any = None,
    include_header: bool = True,
) -> str:
    """Fetch formatted XML messages for the current session.

    Returns formatted message text, empty string when no messages exist,
    or an error message string for invalid input.

    When ``include_header`` is False, returns only ``<message>`` XML blocks
    (suitable for direct LLM summarization).
    """
    if int(group_id) > 0:
        chat_type = "group"
        chat_id = str(group_id)
    else:
        chat_type = "private"
        chat_id = str(user_id)

    time_range_str = str(time_range or "").strip()
    max_count = _get_history_limit(
        runtime_config, "history_summary_fetch_limit", _FALLBACK_MAX_COUNT
    )
    if count is None:
        resolved_count = _DEFAULT_COUNT
    else:
        resolved_count = min(max(int(count), 1), max_count)

    if time_range_str:
        seconds = parse_time_range(time_range_str)
        if seconds is None:
            return f"无法解析时间范围: {time_range_str}(支持格式: 1h, 6h, 1d, 7d)"
        max_time_fetch = _get_history_limit(
            runtime_config,
            "history_summary_time_fetch_limit",
            _FALLBACK_MAX_FETCH_FOR_TIME_FILTER,
        )
        fetch_count = max(resolved_count * 2, max_time_fetch)
        messages = await asyncio.to_thread(
            history_manager.get_recent, chat_id, chat_type, 0, fetch_count
        )
        if messages:
            messages = filter_by_time(messages, seconds)
    else:
        messages = await asyncio.to_thread(
            history_manager.get_recent, chat_id, chat_type, 0, resolved_count
        )

    if not messages:
        return ""

    messages = normalize_messages_for_chat(
        messages, chat_type=chat_type, chat_id=chat_id
    )
    formatted = format_messages_xml(messages)
    if not include_header:
        return formatted

    total = len(messages)
    header = f"共获取 {total} 条消息"
    if time_range_str:
        header += f"(时间范围: {time_range_str})"
    return f"{header}\n\n{formatted}"
