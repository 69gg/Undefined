from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from typing import Any

from Undefined.utils.xml import format_messages_xml

logger = logging.getLogger(__name__)

_TIME_RANGE_PATTERN = re.compile(r"^(\d+)([hHdDwW])$")
_TIME_UNIT_SECONDS = {"h": 3600, "d": 86400, "w": 604800}
_DEFAULT_COUNT = 50

# 以下值仅作为 runtime_config 缺失时的回退
_FALLBACK_MAX_COUNT = 1000
_FALLBACK_MAX_FETCH_FOR_TIME_FILTER = 5000


def _get_history_limit(context: dict[str, Any], key: str, fallback: int) -> int:
    """从 runtime_config 读取历史限制配置。"""
    cfg = context.get("runtime_config")
    if cfg is not None:
        val = getattr(cfg, key, None)
        if isinstance(val, int) and val > 0:
            return val
    return fallback


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
    max_count = _get_history_limit(
        context, "history_summary_fetch_limit", _FALLBACK_MAX_COUNT
    )
    try:
        count = min(max(int(raw_count), 1), max_count)
    except (TypeError, ValueError):
        count = _DEFAULT_COUNT

    if time_range_str:
        seconds = _parse_time_range(time_range_str)
        if seconds is None:
            return f"无法解析时间范围: {time_range_str}(支持格式: 1h, 6h, 1d, 7d)"
        max_time_fetch = _get_history_limit(
            context,
            "history_summary_time_fetch_limit",
            _FALLBACK_MAX_FETCH_FOR_TIME_FILTER,
        )
        fetch_count = max(count * 2, max_time_fetch)
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

    formatted = format_messages_xml(messages)
    total = len(messages)
    header = f"共获取 {total} 条消息"
    if time_range_str:
        header += f"(时间范围: {time_range_str})"
    return f"{header}\n\n{formatted}"
