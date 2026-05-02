from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime, timedelta
from typing import Any

from Undefined.onebot import parse_message_time
from Undefined.utils.group_metrics import clamp_int, datetime_to_ts
from Undefined.utils.message_utils import count_message_types, fetch_group_messages
from Undefined.utils.time_utils import format_datetime, parse_time_range

logger = logging.getLogger(__name__)

_DEFAULT_DAYS = 30
_DEFAULT_MAX_HISTORY_COUNT = 5000
_WEEKDAY_NAMES = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def _runtime_limit(context: dict[str, Any], key: str, fallback: int) -> int:
    config = context.get("runtime_config")
    value = getattr(config, key, None) if config is not None else None
    if isinstance(value, int) and value > 0:
        return value
    return fallback


def _to_bool(raw_value: Any, default: bool) -> bool:
    if raw_value is None:
        return default
    if isinstance(raw_value, bool):
        return raw_value
    if isinstance(raw_value, str):
        normalized = raw_value.strip().lower()
        if normalized in {"1", "true", "yes", "y", "on"}:
            return True
        if normalized in {"0", "false", "no", "n", "off"}:
            return False
    return bool(raw_value)


def _dict_or_empty(raw_value: Any) -> dict[str, Any]:
    if isinstance(raw_value, dict):
        return raw_value
    return {}


def _format_rate(part: int, total: int) -> str:
    if total <= 0:
        return "0.0%"
    return f"{part / total * 100:.1f}%"


def _resolve_time_window(args: dict[str, Any]) -> tuple[datetime, datetime, str | None]:
    start_time = args.get("start_time")
    end_time = args.get("end_time")
    start_text = str(start_time).strip() if start_time is not None else ""
    end_text = str(end_time).strip() if end_time is not None else ""
    start_dt, end_dt = parse_time_range(start_text or None, end_text or None)

    if start_text and start_dt is None:
        return (
            datetime.now(),
            datetime.now(),
            "start_time 格式错误，请使用 YYYY-MM-DD HH:MM:SS",
        )
    if end_text and end_dt is None:
        return (
            datetime.now(),
            datetime.now(),
            "end_time 格式错误，请使用 YYYY-MM-DD HH:MM:SS",
        )

    days = clamp_int(args.get("days"), _DEFAULT_DAYS, 1, 365)
    now_dt = datetime.now()
    if end_dt is None:
        end_dt = now_dt
    if start_dt is None:
        start_dt = end_dt - timedelta(days=days)
    if start_dt > end_dt:
        return start_dt, end_dt, "参数范围错误：start_time 不能晚于 end_time"
    return start_dt, end_dt, None


def _message_preview(message: dict[str, Any], limit: int = 80) -> str:
    raw_message = message.get("message")
    parts: list[str] = []
    if isinstance(raw_message, str):
        parts.append(raw_message)
    elif isinstance(raw_message, list):
        for segment in raw_message:
            if not isinstance(segment, dict):
                continue
            segment_type = str(segment.get("type") or "")
            data = _dict_or_empty(segment.get("data"))
            if segment_type == "text":
                parts.append(str(data.get("text") or ""))
            elif segment_type:
                parts.append(f"[{segment_type}]")
    text = "".join(parts).strip().replace("\n", " ") or "(空消息)"
    if len(text) <= limit:
        return text
    return text[: limit - 8].rstrip() + "..."


async def execute(args: dict[str, Any], context: dict[str, Any]) -> str:
    """统计群消息构成事实数据。"""
    request_id = str(context.get("request_id", "-"))
    group_id = args.get("group_id") or context.get("group_id")
    if group_id is None:
        return "请提供群号（group_id 参数），或者在群聊中调用"

    try:
        group_id = int(group_id)
    except (TypeError, ValueError):
        return "参数类型错误：group_id 必须是整数"
    if group_id <= 0:
        return "参数范围错误：group_id 必须大于 0"

    onebot_client = context.get("onebot_client")
    if not onebot_client:
        return "群消息构成统计功能不可用（OneBot 客户端未设置）"

    start_dt, end_dt, time_error = _resolve_time_window(args)
    if time_error:
        return time_error
    start_ts = datetime_to_ts(start_dt)
    end_ts = datetime_to_ts(end_dt)
    if start_ts is None or end_ts is None:
        return "时间范围转换失败，请检查参数"

    history_cap = max(100, _runtime_limit(context, "history_search_scan_limit", 10000))
    max_history_count = clamp_int(
        args.get("max_history_count"),
        _DEFAULT_MAX_HISTORY_COUNT,
        100,
        history_cap,
    )
    include_samples = _to_bool(args.get("include_samples"), True)
    sample_count = clamp_int(args.get("sample_count"), 3, 1, 10)

    try:
        raw_messages = await fetch_group_messages(
            onebot_client,
            group_id,
            max_history_count,
            start_dt,
        )
    except Exception as exc:
        logger.exception(
            "统计群消息构成失败: group=%s request_id=%s err=%s",
            group_id,
            request_id,
            exc,
        )
        return "统计失败：群消息构成服务暂时不可用，请稍后重试"

    filtered_messages: list[dict[str, Any]] = []
    active_users: set[int] = set()
    hourly_counter: Counter[int] = Counter()
    weekday_counter: Counter[int] = Counter()
    message_times: list[datetime] = []

    for message in raw_messages:
        message_time = parse_message_time(message)
        message_ts = datetime_to_ts(message_time)
        if message_ts is None or message_ts < start_ts or message_ts > end_ts:
            continue
        filtered_messages.append(message)
        message_times.append(message_time)
        hourly_counter[message_time.hour] += 1
        weekday_counter[message_time.weekday()] += 1

        sender = _dict_or_empty(message.get("sender"))
        try:
            user_id = int(sender.get("user_id") or 0)
        except (TypeError, ValueError):
            user_id = 0
        if user_id > 0:
            active_users.add(user_id)

    total_messages = len(filtered_messages)
    lines: list[str] = [f"【群消息构成】群号: {group_id}"]
    lines.append(f"时间范围: {format_datetime(start_dt)} ~ {format_datetime(end_dt)}")
    lines.append(
        f"数据读取: 扫描历史 {len(raw_messages)} 条；窗口有效消息 {total_messages} 条（扫描上限 {max_history_count} 条）"
    )
    lines.append(f"活跃发送者: {len(active_users)} 人")
    lines.append(
        "消息时间覆盖: "
        f"{min(message_times).strftime('%Y-%m-%d %H:%M:%S') if message_times else '无'} ~ "
        f"{max(message_times).strftime('%Y-%m-%d %H:%M:%S') if message_times else '无'}"
    )

    lines.append("")
    lines.append("消息类型分布:")
    type_stats = count_message_types(filtered_messages)
    if type_stats:
        for message_type, amount in sorted(
            type_stats.items(), key=lambda item: item[1], reverse=True
        ):
            lines.append(
                f"- {message_type}: {amount} 条（{_format_rate(amount, total_messages)}）"
            )
    else:
        lines.append("- 暂无消息类型数据")

    lines.append("")
    lines.append("活跃时段 Top:")
    if hourly_counter:
        for hour, amount in hourly_counter.most_common(5):
            lines.append(f"- {hour:02d}:00-{hour:02d}:59: {amount} 条")
    else:
        lines.append("- 暂无时段数据")

    lines.append("")
    lines.append("活跃星期分布:")
    if weekday_counter:
        for weekday, amount in weekday_counter.most_common():
            lines.append(f"- {_WEEKDAY_NAMES[weekday]}: {amount} 条")
    else:
        lines.append("- 暂无星期数据")

    if include_samples and filtered_messages:
        lines.append("")
        lines.append(f"最近消息样本（{min(sample_count, len(filtered_messages))} 条）:")
        for message in sorted(filtered_messages, key=parse_message_time, reverse=True)[
            :sample_count
        ]:
            sender = _dict_or_empty(message.get("sender"))
            sender_name = (
                sender.get("card")
                or sender.get("nickname")
                or sender.get("user_id")
                or "未知"
            )
            lines.append(
                f"- {parse_message_time(message).strftime('%Y-%m-%d %H:%M:%S')} "
                f"{sender_name}: {_message_preview(message)}"
            )

    return "\n".join(lines)
