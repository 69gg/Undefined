from __future__ import annotations

import logging
import time
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


def _score_hybrid(
    message_count: int, active_days: int, last_sent_ts: int, now_ts: int
) -> int:
    recency_bonus = 0
    if last_sent_ts > 0:
        days_since_last = max(0, int((now_ts - last_sent_ts) / 86400))
        recency_bonus = max(0, 10 - days_since_last)
    return message_count * 3 + active_days * 5 + recency_bonus


async def execute(args: dict[str, Any], context: dict[str, Any]) -> str:
    """分析群成员活跃度（支持 member_list/history/hybrid 三种数据源）。"""
    request_id = str(context.get("request_id", "-"))
    group_id = args.get("group_id") or context.get("group_id")
    threshold_days_raw = args.get("threshold_days", 30)
    display_count = clamp_int(args.get("count"), default=10, min_value=1, max_value=100)
    source = str(args.get("source") or "hybrid").strip().lower()
    if source not in {"member_list", "history", "hybrid"}:
        return "参数错误：source 仅支持 member_list/history/hybrid"

    try:
        threshold_days = int(threshold_days_raw)
    except (TypeError, ValueError):
        return "参数类型错误：threshold_days 必须是整数"
    if threshold_days <= 0:
        return "参数范围错误：threshold_days 必须大于 0"

    include_zero = bool(args.get("include_zero", False))
    history_days = clamp_int(
        args.get("history_days"), default=threshold_days, min_value=1, max_value=365
    )
    max_history_count = clamp_int(
        args.get("max_history_count"), default=3000, min_value=100, max_value=5000
    )
    start_time = args.get("start_time")
    end_time = args.get("end_time")
    start_dt, end_dt = parse_time_range(start_time, end_time)
    if start_time and start_dt is None:
        return "start_time 格式错误，请使用 YYYY-MM-DD HH:MM:SS"
    if end_time and end_dt is None:
        return "end_time 格式错误，请使用 YYYY-MM-DD HH:MM:SS"
    if start_dt and end_dt and start_dt > end_dt:
        return "参数范围错误：start_time 不能晚于 end_time"

    if group_id is None:
        return "请提供群号（group_id 参数），或者在群聊中调用"

    try:
        group_id = int(group_id)
    except (ValueError, TypeError):
        return "参数类型错误：group_id 必须是整数"

    onebot_client = context.get("onebot_client")
    if not onebot_client:
        return "获取群成员活跃度功能不可用（OneBot 客户端未设置）"

    try:
        member_list: list[dict[str, Any]] = await onebot_client.get_group_member_list(
            group_id
        )

        if not member_list:
            return f"未能获取到群 {group_id} 的成员列表"

        now_ts = int(time.time())
        threshold_ts = now_ts - (threshold_days * 86400)

        active_members: list[dict[str, Any]] = []
        inactive_members: list[dict[str, Any]] = []
        member_map: dict[int, dict[str, Any]] = {}

        for member in member_list:
            last_sent = parse_unix_timestamp(member.get("last_sent_time"))
            if last_sent == 0 or last_sent < threshold_ts:
                inactive_members.append(member)
            else:
                active_members.append(member)

            raw_uid = member.get("user_id")
            if raw_uid is None:
                continue
            try:
                uid = int(raw_uid)
            except (TypeError, ValueError):
                continue
            member_map[uid] = member

        active_members.sort(
            key=lambda item: parse_unix_timestamp(item.get("last_sent_time")),
            reverse=True,
        )
        inactive_members.sort(
            key=lambda item: parse_unix_timestamp(item.get("last_sent_time")),
        )

        history_counts: dict[int, int] = defaultdict(int)
        history_active_days: dict[int, set[str]] = defaultdict(set)
        history_message_total = 0
        history_start_dt: datetime | None = None
        history_end_dt: datetime | None = None

        if source in {"history", "hybrid"}:
            now_dt = datetime.now()
            history_start_dt = start_dt or (now_dt - timedelta(days=history_days))
            history_end_dt = end_dt or now_dt

            history_start_ts = datetime_to_ts(history_start_dt)
            history_end_ts = datetime_to_ts(history_end_dt)
            if history_start_ts is None or history_end_ts is None:
                return "历史时间范围转换失败，请检查参数"
            if history_start_ts > history_end_ts:
                return "参数范围错误：start_time 不能晚于 end_time"

            history_messages = await fetch_group_messages(
                onebot_client,
                group_id,
                max_history_count,
                history_start_dt,
            )

            for msg in history_messages:
                sender = msg.get("sender") or {}
                raw_uid = sender.get("user_id")
                if raw_uid is None:
                    continue
                try:
                    uid = int(raw_uid)
                except (TypeError, ValueError):
                    continue
                if uid not in member_map:
                    continue

                msg_dt = parse_message_time(msg)
                msg_ts = datetime_to_ts(msg_dt)
                if msg_ts is None:
                    continue
                if msg_ts < history_start_ts or msg_ts > history_end_ts:
                    continue

                history_counts[uid] += 1
                history_active_days[uid].add(msg_dt.strftime("%Y-%m-%d"))
                history_message_total += 1

        result_parts: list[str] = [f"【群活跃度统计】群号: {group_id}"]
        result_parts.append(f"分析模式: {source}")
        result_parts.append(f"总成员数: {len(member_list)}")
        result_parts.append(
            f"活跃成员（最近{threshold_days}天内发言）: {len(active_members)}"
        )
        result_parts.append(f"非活跃成员: {len(inactive_members)}")

        if member_list:
            active_rate = len(active_members) / len(member_list) * 100
            result_parts.append(f"活跃率: {active_rate:.1f}%")

        ranking_items: list[dict[str, Any]] = []
        if source == "member_list":
            for member in active_members:
                ranking_items.append(
                    {
                        "member": member,
                        "message_count": None,
                        "active_days": None,
                        "score": None,
                        "last_sent_ts": parse_unix_timestamp(
                            member.get("last_sent_time")
                        ),
                    }
                )
        else:
            if history_start_dt and history_end_dt:
                result_parts.append(
                    f"历史窗口: {format_datetime(history_start_dt)} ~ {format_datetime(history_end_dt)}"
                )
                result_parts.append(
                    f"历史消息计数: {history_message_total} 条（最多读取 {max_history_count} 条）"
                )

            window_active_users = sum(
                1 for value in history_counts.values() if value > 0
            )
            result_parts.append(f"窗口内有发言成员: {window_active_users}")
            if member_list:
                avg_messages = history_message_total / len(member_list)
                result_parts.append(f"窗口内人均消息: {avg_messages:.2f}")

            for uid, member in member_map.items():
                message_count = history_counts.get(uid, 0)
                if source == "history" and not include_zero and message_count <= 0:
                    continue

                active_days = len(history_active_days.get(uid, set()))
                last_sent_ts = parse_unix_timestamp(member.get("last_sent_time"))
                score = _score_hybrid(message_count, active_days, last_sent_ts, now_ts)

                ranking_items.append(
                    {
                        "member": member,
                        "message_count": message_count,
                        "active_days": active_days,
                        "score": score,
                        "last_sent_ts": last_sent_ts,
                    }
                )

            if source == "history":
                ranking_items.sort(
                    key=lambda item: (
                        int(item.get("message_count") or 0),
                        int(item.get("active_days") or 0),
                        int(item.get("last_sent_ts") or 0),
                    ),
                    reverse=True,
                )
            else:
                ranking_items.sort(
                    key=lambda item: (
                        int(item.get("score") or 0),
                        int(item.get("message_count") or 0),
                        int(item.get("active_days") or 0),
                        int(item.get("last_sent_ts") or 0),
                    ),
                    reverse=True,
                )

        if ranking_items:
            result_parts.append(
                f"最活跃成员 Top {min(display_count, len(ranking_items))}:"
            )
            for index, item in enumerate(ranking_items[:display_count], start=1):
                member = item["member"]
                name = member_display_name(member)
                member_uid = member.get("user_id")
                last_desc = format_timestamp(int(item.get("last_sent_ts") or 0))
                if source == "member_list":
                    result_parts.append(
                        f"{index}. {name} ({member_uid}) | 最后发言: {last_desc}"
                    )
                elif source == "history":
                    result_parts.append(
                        f"{index}. {name} ({member_uid}) | 窗口消息: {item['message_count']} | "
                        f"活跃天数: {item['active_days']} | 最后发言: {last_desc}"
                    )
                else:
                    result_parts.append(
                        f"{index}. {name} ({member_uid}) | 综合分: {item['score']} | "
                        f"窗口消息: {item['message_count']} | 活跃天数: {item['active_days']} | "
                        f"最后发言: {last_desc}"
                    )

        if inactive_members:
            result_parts.append(
                f"潜水成员 Top {min(display_count, len(inactive_members))}:"
            )
            for index, member in enumerate(inactive_members[:display_count], start=1):
                name = member_display_name(member)
                member_uid = member.get("user_id")
                last_sent = parse_unix_timestamp(member.get("last_sent_time"))
                last_desc = (
                    "从未发言" if last_sent <= 0 else format_timestamp(last_sent)
                )
                result_parts.append(
                    f"{index}. {name} ({member_uid}) | 最后发言: {last_desc}"
                )

        return "\n".join(result_parts)

    except Exception as exc:
        logger.exception(
            "获取群活跃度失败: group=%s request_id=%s err=%s",
            group_id,
            request_id,
            exc,
        )
        return "获取失败：群活跃度服务暂时不可用，请稍后重试"
