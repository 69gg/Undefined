from __future__ import annotations

import logging
import time
from collections import Counter, defaultdict
from typing import Any

from Undefined.utils.group_metrics import (
    clamp_int,
    format_timestamp,
    member_display_name,
    parse_member_level,
    parse_unix_timestamp,
    role_to_cn,
)

logger = logging.getLogger(__name__)


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


def _format_rate(part: int, total: int) -> str:
    if total <= 0:
        return "0.0%"
    return f"{part / total * 100:.1f}%"


def _days_since(now_ts: int, past_ts: int) -> int | None:
    if past_ts <= 0:
        return None
    return max(0, int((now_ts - past_ts) / 86400))


async def execute(args: dict[str, Any], context: dict[str, Any]) -> str:
    """统计群成员结构事实数据。"""
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

    include_examples = _to_bool(args.get("include_examples"), True)
    example_count = clamp_int(args.get("example_count"), 3, 1, 10)

    onebot_client = context.get("onebot_client")
    if not onebot_client:
        return "群成员结构统计功能不可用（OneBot 客户端未设置）"

    try:
        member_list: list[dict[str, Any]] = await onebot_client.get_group_member_list(
            group_id
        )
    except Exception as exc:
        logger.exception(
            "统计群成员结构失败: group=%s request_id=%s err=%s",
            group_id,
            request_id,
            exc,
        )
        return "统计失败：群成员结构服务暂时不可用，请稍后重试"

    if not member_list:
        return f"未能获取到群 {group_id} 的成员列表"

    now_ts = int(time.time())
    total_members = len(member_list)
    role_counter: Counter[str] = Counter()
    role_samples: dict[str, list[str]] = defaultdict(list)
    level_values: list[int] = []
    unknown_level_count = 0
    join_timestamps: list[int] = []
    last_sent_timestamps: list[int] = []
    never_spoke_count = 0
    joined_7d = 0
    joined_30d = 0
    joined_90d = 0
    active_7d = 0
    active_30d = 0
    inactive_90d = 0

    for member in member_list:
        role_text = role_to_cn(member.get("role"))
        role_counter[role_text] += 1
        if include_examples and len(role_samples[role_text]) < example_count:
            role_samples[role_text].append(
                f"{member_display_name(member)}({member.get('user_id')})"
            )

        level = parse_member_level(member.get("level"))
        if level is None:
            unknown_level_count += 1
        else:
            level_values.append(level)

        join_ts = parse_unix_timestamp(member.get("join_time"))
        if join_ts > 0:
            join_timestamps.append(join_ts)
            join_days = _days_since(now_ts, join_ts)
            if join_days is not None and join_days <= 7:
                joined_7d += 1
            if join_days is not None and join_days <= 30:
                joined_30d += 1
            if join_days is not None and join_days <= 90:
                joined_90d += 1

        last_sent_ts = parse_unix_timestamp(member.get("last_sent_time"))
        if last_sent_ts <= 0:
            never_spoke_count += 1
            continue
        last_sent_timestamps.append(last_sent_ts)
        silent_days = _days_since(now_ts, last_sent_ts)
        if silent_days is not None and silent_days <= 7:
            active_7d += 1
        if silent_days is not None and silent_days <= 30:
            active_30d += 1
        if silent_days is not None and silent_days >= 90:
            inactive_90d += 1

    lines: list[str] = [f"【群成员结构】群号: {group_id}"]
    lines.append(f"成员总数: {total_members}")
    lines.append("")
    lines.append("角色分布:")
    for role_text, amount in role_counter.most_common():
        lines.append(
            f"- {role_text}: {amount} 人（{_format_rate(amount, total_members)}）"
        )
        if include_examples and role_samples.get(role_text):
            lines.append(f"  样例: {'，'.join(role_samples[role_text])}")

    lines.append("")
    lines.append("等级概览:")
    if level_values:
        average_level = sum(level_values) / len(level_values)
        lines.append(f"- 已识别等级成员: {len(level_values)} 人")
        lines.append(f"- 最高等级: Lv.{max(level_values)}")
        lines.append(f"- 最低等级: Lv.{min(level_values)}")
        lines.append(f"- 平均等级: Lv.{average_level:.1f}")
    else:
        lines.append("- 暂无可用等级数据")
    if unknown_level_count > 0:
        lines.append(f"- 等级未知: {unknown_level_count} 人")

    lines.append("")
    lines.append("入群结构:")
    lines.append(f"- 最近 7 天入群: {joined_7d} 人")
    lines.append(f"- 最近 30 天入群: {joined_30d} 人")
    lines.append(f"- 最近 90 天入群: {joined_90d} 人")
    lines.append(
        f"- 入群时间覆盖: {format_timestamp(min(join_timestamps) if join_timestamps else 0)} ~ "
        f"{format_timestamp(max(join_timestamps) if join_timestamps else 0)}"
    )

    lines.append("")
    lines.append("最后发言结构:")
    lines.append(f"- 最近 7 天发言: {active_7d} 人")
    lines.append(f"- 最近 30 天发言: {active_30d} 人")
    lines.append(f"- 超过 90 天未发言: {inactive_90d} 人")
    lines.append(f"- 从未发言/无记录: {never_spoke_count} 人")
    lines.append(
        f"- 最后发言覆盖: {format_timestamp(min(last_sent_timestamps) if last_sent_timestamps else 0)} ~ "
        f"{format_timestamp(max(last_sent_timestamps) if last_sent_timestamps else 0)}"
    )

    return "\n".join(lines)
