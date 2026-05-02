from __future__ import annotations

import logging
import time
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


def _days_since(now_ts: int, past_ts: int) -> int | None:
    if past_ts <= 0:
        return None
    delta = now_ts - past_ts
    return max(0, int(delta / 86400))


async def execute(args: dict[str, Any], context: dict[str, Any]) -> str:
    """识别群成员活跃风险。"""
    request_id = str(context.get("request_id", "-"))
    group_id = args.get("group_id") or context.get("group_id")

    if group_id is None:
        return "请提供群号（group_id 参数），或者在群聊中调用"

    try:
        group_id = int(group_id)
    except (TypeError, ValueError):
        return "参数类型错误：group_id 必须是整数"

    new_member_days = clamp_int(
        args.get("new_member_days"), default=30, min_value=1, max_value=365
    )
    silent_days = clamp_int(
        args.get("silent_days"), default=14, min_value=1, max_value=365
    )
    long_inactive_days = clamp_int(
        args.get("long_inactive_days"), default=60, min_value=1, max_value=3650
    )
    high_level_threshold = clamp_int(
        args.get("high_level_threshold"), default=30, min_value=1, max_value=999
    )
    count = clamp_int(args.get("count"), default=20, min_value=1, max_value=100)

    onebot_client = context.get("onebot_client")
    if not onebot_client:
        return "活跃风险识别功能不可用（OneBot 客户端未设置）"

    try:
        member_list: list[dict[str, Any]] = await onebot_client.get_group_member_list(
            group_id
        )
        if not member_list:
            return f"未能获取到群 {group_id} 的成员列表"

        now_ts = int(time.time())
        never_spoke_count = 0
        long_inactive_count = 0
        new_member_silent_count = 0
        high_level_low_activity_count = 0

        risk_items: list[dict[str, Any]] = []

        for member in member_list:
            join_ts = parse_unix_timestamp(member.get("join_time"))
            last_sent_ts = parse_unix_timestamp(member.get("last_sent_time"))
            level = parse_member_level(member.get("level"))
            days_since_join = _days_since(now_ts, join_ts)
            days_since_last = _days_since(now_ts, last_sent_ts)

            score = 0
            tags: list[str] = []

            if last_sent_ts <= 0:
                never_spoke_count += 1
                score += 45
                tags.append("从未发言")

            if days_since_last is not None and days_since_last >= long_inactive_days:
                long_inactive_count += 1
                score += 25
                tags.append(f"长期潜水>{long_inactive_days}天")

            if days_since_join is not None and days_since_join <= new_member_days:
                if days_since_last is None or days_since_last >= silent_days:
                    new_member_silent_count += 1
                    score += 30
                    tags.append(f"新成员沉默(<= {new_member_days}天)")

            if level is not None and level >= high_level_threshold:
                if days_since_last is None or days_since_last >= silent_days:
                    high_level_low_activity_count += 1
                    score += 20
                    tags.append(f"高等级低活跃(Lv>={high_level_threshold})")

            if score <= 0:
                continue

            role_text = role_to_cn(member.get("role"))
            risk_items.append(
                {
                    "score": score,
                    "member": member,
                    "tags": tags,
                    "level": level,
                    "role_text": role_text,
                    "join_ts": join_ts,
                    "last_sent_ts": last_sent_ts,
                    "days_since_last": days_since_last,
                }
            )

        if not risk_items:
            return f"群 {group_id} 暂未识别到明显的活跃风险成员"

        risk_items.sort(
            key=lambda item: (
                int(item.get("score", 0)),
                int(item.get("days_since_last") or 0),
                -int(item.get("join_ts") or 0),
            ),
            reverse=True,
        )
        risk_items = risk_items[:count]

        lines: list[str] = [f"【活跃风险识别】群号: {group_id}"]
        lines.append(f"成员总数: {len(member_list)}，风险成员: {len(risk_items)}")
        lines.append(
            f"风险统计: 从未发言={never_spoke_count}，长期潜水={long_inactive_count}，"
            f"新成员沉默={new_member_silent_count}，高等级低活跃={high_level_low_activity_count}"
        )
        lines.append(f"展示前 {len(risk_items)} 人:")

        for index, item in enumerate(risk_items, start=1):
            member = item["member"]
            user_id = member.get("user_id")
            level_text = (
                str(item.get("level")) if item.get("level") is not None else "未知"
            )
            tag_text = "、".join(item.get("tags", []))
            lines.append(
                f"{index}. {member_display_name(member)} ({user_id}) [{item['role_text']}] "
                f"Lv.{level_text} | 风险分: {item['score']} | 标签: {tag_text}"
            )
            lines.append(
                f"   入群: {format_timestamp(int(item.get('join_ts') or 0))} | "
                f"最后发言: {format_timestamp(int(item.get('last_sent_ts') or 0))}"
            )

        return "\n".join(lines)
    except Exception as exc:
        logger.exception(
            "识别群活跃风险失败: group=%s request_id=%s err=%s",
            group_id,
            request_id,
            exc,
        )
        return "识别失败：活跃风险识别服务暂时不可用，请稍后重试"
