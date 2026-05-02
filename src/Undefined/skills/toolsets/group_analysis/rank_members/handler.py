from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from Undefined.onebot import parse_message_time
from Undefined.utils.group_metrics import (
    clamp_int,
    datetime_to_ts,
    format_timestamp,
    member_display_name,
    parse_unix_timestamp,
)
from Undefined.utils.message_utils import fetch_group_messages
from Undefined.utils.time_utils import format_datetime, parse_time_range

logger = logging.getLogger(__name__)


def _build_score(
    message_count: int, active_days: int, last_sent_ts: int, now_ts: int
) -> int:
    """构建可解释的活跃度综合分。"""
    recency_bonus = 0
    if last_sent_ts > 0:
        days_since_last = max(0, int((now_ts - last_sent_ts) / 86400))
        recency_bonus = max(0, 10 - days_since_last)
    return message_count * 3 + active_days * 5 + recency_bonus


async def execute(args: dict[str, Any], context: dict[str, Any]) -> str:
    """按历史消息活跃度排行成员。"""
    request_id = str(context.get("request_id", "-"))
    group_id = args.get("group_id") or context.get("group_id")

    if group_id is None:
        return "请提供群号（group_id 参数），或者在群聊中调用"

    try:
        group_id = int(group_id)
    except (TypeError, ValueError):
        return "参数类型错误：group_id 必须是整数"

    days = clamp_int(args.get("days"), default=7, min_value=1, max_value=180)
    max_history_count = clamp_int(
        args.get("max_history_count"), default=3000, min_value=100, max_value=5000
    )
    count = clamp_int(args.get("count"), default=20, min_value=1, max_value=100)
    include_zero = bool(args.get("include_zero", False))
    sort_by = str(args.get("sort_by") or "score").strip()
    if sort_by not in {"score", "message_count", "active_days", "last_sent_time"}:
        return "参数错误：sort_by 仅支持 score/message_count/active_days/last_sent_time"

    start_time = args.get("start_time")
    end_time = args.get("end_time")
    start_dt, end_dt = parse_time_range(start_time, end_time)
    if start_time and start_dt is None:
        return "start_time 格式错误，请使用 YYYY-MM-DD HH:MM:SS"
    if end_time and end_dt is None:
        return "end_time 格式错误，请使用 YYYY-MM-DD HH:MM:SS"

    now_dt = datetime.now()
    if start_dt is None:
        start_dt = now_dt - timedelta(days=days)
    if end_dt is None:
        end_dt = now_dt
    if start_dt > end_dt:
        return "参数范围错误：start_time 不能晚于 end_time"

    start_ts = datetime_to_ts(start_dt)
    end_ts = datetime_to_ts(end_dt)
    if start_ts is None or end_ts is None:
        return "时间范围转换失败，请检查参数"

    onebot_client = context.get("onebot_client")
    if not onebot_client:
        return "成员活跃排行功能不可用（OneBot 客户端未设置）"

    try:
        member_list: list[dict[str, Any]] = await onebot_client.get_group_member_list(
            group_id
        )
        if not member_list:
            return f"未能获取到群 {group_id} 的成员列表"

        member_map: dict[int, dict[str, Any]] = {}
        for member in member_list:
            raw_user_id = member.get("user_id")
            if raw_user_id is None:
                continue
            try:
                user_id = int(raw_user_id)
            except (TypeError, ValueError):
                continue
            member_map[user_id] = member

        all_messages = await fetch_group_messages(
            onebot_client,
            group_id,
            max_history_count,
            start_dt,
        )

        message_counts: dict[int, int] = defaultdict(int)
        active_day_sets: dict[int, set[str]] = defaultdict(set)

        for msg in all_messages:
            sender = msg.get("sender") or {}
            try:
                user_id = int(sender.get("user_id") or 0)
            except (TypeError, ValueError):
                continue
            if user_id not in member_map:
                continue

            msg_time = parse_message_time(msg)
            msg_ts = datetime_to_ts(msg_time)
            if msg_ts is None:
                continue
            if msg_ts < start_ts or msg_ts > end_ts:
                continue

            message_counts[user_id] += 1
            active_day_sets[user_id].add(msg_time.strftime("%Y-%m-%d"))

        now_ts = datetime_to_ts(now_dt) or end_ts
        ranking: list[dict[str, Any]] = []
        for user_id, member in member_map.items():
            message_count = message_counts.get(user_id, 0)
            if not include_zero and message_count <= 0:
                continue

            active_days = len(active_day_sets.get(user_id, set()))
            last_sent_ts = parse_unix_timestamp(member.get("last_sent_time"))
            score = _build_score(message_count, active_days, last_sent_ts, now_ts)

            ranking.append(
                {
                    "user_id": user_id,
                    "member": member,
                    "message_count": message_count,
                    "active_days": active_days,
                    "last_sent_ts": last_sent_ts,
                    "score": score,
                }
            )

        if not ranking:
            return (
                f"群 {group_id} 在 {format_datetime(start_dt)} ~ {format_datetime(end_dt)} "
                "范围内没有可排行数据"
            )

        ranking.sort(
            key=lambda item: (
                int(item.get(sort_by, 0)),
                int(item.get("message_count", 0)),
                int(item.get("active_days", 0)),
                int(item.get("last_sent_ts", 0)),
            ),
            reverse=True,
        )
        ranking = ranking[:count]

        total_messages = sum(int(item.get("message_count", 0)) for item in ranking)
        lines: list[str] = [f"【群成员活跃排行】群号: {group_id}"]
        lines.append(
            f"时间范围: {format_datetime(start_dt)} ~ {format_datetime(end_dt)}"
        )
        lines.append(
            f"读取历史消息: {len(all_messages)} 条，入榜人数: {len(ranking)}，榜单总消息数: {total_messages}"
        )
        lines.append(f"排序字段: {sort_by}")

        for index, item in enumerate(ranking, start=1):
            member = item["member"]
            user_id = item["user_id"]
            lines.append(
                f"{index}. {member_display_name(member)} ({user_id}) | "
                f"消息: {item['message_count']} | 活跃天数: {item['active_days']} | "
                f"综合分: {item['score']} | 最后发言: {format_timestamp(item['last_sent_ts'])}"
            )

        return "\n".join(lines)
    except Exception as exc:
        logger.exception(
            "群成员活跃排行失败: group=%s request_id=%s err=%s",
            group_id,
            request_id,
            exc,
        )
        return "排行失败：成员活跃排行服务暂时不可用，请稍后重试"
