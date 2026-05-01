from __future__ import annotations

import logging
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Any

from Undefined.onebot import parse_message_time
from Undefined.utils.group_metrics import clamp_int, datetime_to_ts, member_display_name
from Undefined.utils.message_utils import fetch_group_messages
from Undefined.utils.time_utils import format_datetime, parse_time_range

logger = logging.getLogger(__name__)


def _to_bucket(dt: datetime, granularity: str) -> str:
    if granularity == "week":
        year, week, _ = dt.isocalendar()
        return f"{year}-W{week:02d}"
    return dt.strftime("%Y-%m-%d")


def _render_bar(current: int, max_value: int, width: int = 20) -> str:
    if max_value <= 0 or current <= 0:
        return ""
    filled = max(1, int(round(current / max_value * width)))
    return "#" * min(width, filled)


async def execute(args: dict[str, Any], context: dict[str, Any]) -> str:
    """分析群聊活跃趋势。"""
    request_id = str(context.get("request_id", "-"))
    group_id = args.get("group_id") or context.get("group_id")

    if group_id is None:
        return "请提供群号（group_id 参数），或者在群聊中调用"

    try:
        group_id = int(group_id)
    except (TypeError, ValueError):
        return "参数类型错误：group_id 必须是整数"

    days = clamp_int(args.get("days"), default=30, min_value=1, max_value=365)
    max_history_count = clamp_int(
        args.get("max_history_count"), default=5000, min_value=100, max_value=5000
    )
    top_count = clamp_int(args.get("top_count"), default=5, min_value=1, max_value=20)
    granularity = str(args.get("granularity") or "day").strip().lower()
    if granularity not in {"day", "week"}:
        return "参数错误：granularity 仅支持 day/week"

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
        return "群活跃趋势分析功能不可用（OneBot 客户端未设置）"

    try:
        all_messages = await fetch_group_messages(
            onebot_client,
            group_id,
            max_history_count,
            start_dt,
        )

        bucket_counts: Counter[str] = Counter()
        bucket_active_users: dict[str, set[int]] = defaultdict(set)
        user_message_counts: Counter[int] = Counter()

        for msg in all_messages:
            msg_time = parse_message_time(msg)
            msg_ts = datetime_to_ts(msg_time)
            if msg_ts is None or msg_ts < start_ts or msg_ts > end_ts:
                continue

            sender = msg.get("sender") or {}
            try:
                user_id = int(sender.get("user_id") or 0)
            except (TypeError, ValueError):
                user_id = 0
            if user_id <= 0:
                continue

            bucket = _to_bucket(msg_time, granularity)
            bucket_counts[bucket] += 1
            bucket_active_users[bucket].add(user_id)
            user_message_counts[user_id] += 1

        if not bucket_counts:
            return (
                f"群 {group_id} 在 {format_datetime(start_dt)} ~ {format_datetime(end_dt)} "
                "范围内没有可用消息数据"
            )

        member_name_map: dict[int, str] = {}
        try:
            member_list: list[
                dict[str, Any]
            ] = await onebot_client.get_group_member_list(group_id)
            for member in member_list:
                try:
                    uid = int(member.get("user_id") or 0)
                except (TypeError, ValueError):
                    continue
                if uid > 0:
                    member_name_map[uid] = member_display_name(member)
        except Exception:
            logger.debug("获取成员列表失败，趋势分析将不显示成员昵称")

        total_messages = sum(bucket_counts.values())
        all_active_users: set[int] = set()
        for users in bucket_active_users.values():
            all_active_users.update(users)

        peak_bucket, peak_count = bucket_counts.most_common(1)[0]
        max_count = peak_count

        lines: list[str] = [f"【群活跃趋势】群号: {group_id}"]
        lines.append(
            f"时间范围: {format_datetime(start_dt)} ~ {format_datetime(end_dt)}"
        )
        lines.append(
            f"总消息数: {total_messages}，活跃成员数: {len(all_active_users)}，峰值: {peak_bucket} ({peak_count} 条)"
        )
        lines.append(f"统计粒度: {granularity}")
        lines.append("趋势明细:")

        for bucket in sorted(bucket_counts.keys()):
            count = bucket_counts[bucket]
            active_users = len(bucket_active_users.get(bucket, set()))
            bar = _render_bar(count, max_count)
            lines.append(f"- {bucket}: {count} 条, {active_users} 人 {bar}")

        lines.append(f"最活跃成员 Top {top_count}:")
        for index, (uid, msg_count) in enumerate(
            user_message_counts.most_common(top_count), start=1
        ):
            name = member_name_map.get(uid, str(uid))
            lines.append(f"{index}. {name} ({uid}) - {msg_count} 条")

        return "\n".join(lines)
    except Exception as exc:
        logger.exception(
            "分析群活跃趋势失败: group=%s request_id=%s err=%s",
            group_id,
            request_id,
            exc,
        )
        return "分析失败：群活跃趋势服务暂时不可用，请稍后重试"
