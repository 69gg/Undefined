from __future__ import annotations

import logging
import re
import time
from typing import Any

from Undefined.utils.group_metrics import (
    clamp_int,
    datetime_to_ts,
    format_timestamp,
    member_display_name,
    parse_member_level,
    parse_unix_timestamp,
    role_to_cn,
)
from Undefined.utils.time_utils import format_datetime, parse_time_range

logger = logging.getLogger(__name__)


def _contains_keyword(member: dict[str, Any], keyword: str) -> bool:
    if not keyword:
        return True
    kw = keyword.lower().strip()
    if not kw:
        return True
    card = str(member.get("card") or "").lower()
    nickname = str(member.get("nickname") or "").lower()
    return kw in card or kw in nickname


def _build_sort_key(sort_by: str, member: dict[str, Any]) -> int:
    if sort_by == "join_time":
        return parse_unix_timestamp(member.get("join_time"))
    if sort_by == "level":
        level = parse_member_level(member.get("level"))
        return level if level is not None else -1
    if sort_by == "user_id":
        try:
            return int(member.get("user_id") or 0)
        except (TypeError, ValueError):
            return 0
    return parse_unix_timestamp(member.get("last_sent_time"))


async def execute(args: dict[str, Any], context: dict[str, Any]) -> str:
    """多条件筛选群成员。"""
    request_id = str(context.get("request_id", "-"))
    group_id = args.get("group_id") or context.get("group_id")

    if group_id is None:
        return "请提供群号（group_id 参数），或者在群聊中调用"

    try:
        group_id = int(group_id)
    except (TypeError, ValueError):
        return "参数类型错误：group_id 必须是整数"

    role_filter = args.get("role")
    level_min = args.get("level_min")
    level_max = args.get("level_max")
    level_regex_text = str(args.get("level_regex") or "").strip()
    join_start_time = args.get("join_start_time")
    join_end_time = args.get("join_end_time")
    active_within_days = args.get("active_within_days")
    inactive_over_days = args.get("inactive_over_days")
    name_keyword = str(args.get("name_keyword") or "").strip()
    title_keyword = str(args.get("title_keyword") or "").strip().lower()
    sort_by = str(args.get("sort_by") or "last_sent_time").strip()
    sort_order = str(args.get("sort_order") or "desc").strip().lower()
    offset = clamp_int(args.get("offset"), default=0, min_value=0, max_value=5000)
    count = clamp_int(args.get("count"), default=20, min_value=1, max_value=200)

    if level_min is not None:
        try:
            level_min = int(level_min)
        except (TypeError, ValueError):
            return "参数类型错误：level_min 必须是整数"
    if level_max is not None:
        try:
            level_max = int(level_max)
        except (TypeError, ValueError):
            return "参数类型错误：level_max 必须是整数"
    if level_min is not None and level_max is not None and level_min > level_max:
        return "参数范围错误：level_min 不能大于 level_max"

    regex_pattern: re.Pattern[str] | None = None
    if level_regex_text:
        try:
            regex_pattern = re.compile(level_regex_text)
        except re.error:
            return "参数错误：level_regex 不是合法正则表达式"

    for field_name, raw_value in (
        ("active_within_days", active_within_days),
        ("inactive_over_days", inactive_over_days),
    ):
        if raw_value is None:
            continue
        try:
            parsed = int(raw_value)
        except (TypeError, ValueError):
            return f"参数类型错误：{field_name} 必须是整数"
        if parsed < 0:
            return f"参数范围错误：{field_name} 必须为非负整数"
        if field_name == "active_within_days":
            active_within_days = parsed
        else:
            inactive_over_days = parsed

    start_dt, end_dt = parse_time_range(join_start_time, join_end_time)
    if join_start_time and start_dt is None:
        return "join_start_time 格式错误，请使用 YYYY-MM-DD HH:MM:SS"
    if join_end_time and end_dt is None:
        return "join_end_time 格式错误，请使用 YYYY-MM-DD HH:MM:SS"
    if start_dt and end_dt and start_dt > end_dt:
        return "参数范围错误：join_start_time 不能晚于 join_end_time"

    join_start_ts = datetime_to_ts(start_dt)
    join_end_ts = datetime_to_ts(end_dt)

    onebot_client = context.get("onebot_client")
    if not onebot_client:
        return "筛选群成员功能不可用（OneBot 客户端未设置）"

    if sort_by not in {"last_sent_time", "join_time", "level", "user_id"}:
        return "参数错误：sort_by 仅支持 last_sent_time/join_time/level/user_id"
    if sort_order not in {"asc", "desc"}:
        return "参数错误：sort_order 仅支持 asc/desc"

    try:
        member_list: list[dict[str, Any]] = await onebot_client.get_group_member_list(
            group_id
        )
        if not member_list:
            return f"未能获取到群 {group_id} 的成员列表"

        now_ts = int(time.time())
        active_threshold = (
            now_ts - int(active_within_days) * 86400
            if active_within_days is not None
            else None
        )
        inactive_threshold = (
            now_ts - int(inactive_over_days) * 86400
            if inactive_over_days is not None
            else None
        )

        filtered: list[dict[str, Any]] = []
        for member in member_list:
            role = str(member.get("role") or "member")
            if role_filter and role != role_filter:
                continue

            level = parse_member_level(member.get("level"))
            if level_min is not None and (level is None or level < int(level_min)):
                continue
            if level_max is not None and (level is None or level > int(level_max)):
                continue

            if regex_pattern is not None:
                level_raw = str(member.get("level") or "")
                if not regex_pattern.search(level_raw):
                    continue

            join_ts = parse_unix_timestamp(member.get("join_time"))
            if join_start_ts is not None and (join_ts <= 0 or join_ts < join_start_ts):
                continue
            if join_end_ts is not None and (join_ts <= 0 or join_ts > join_end_ts):
                continue

            last_sent_ts = parse_unix_timestamp(member.get("last_sent_time"))
            if active_threshold is not None and last_sent_ts < active_threshold:
                continue
            if inactive_threshold is not None and last_sent_ts > inactive_threshold:
                continue

            if not _contains_keyword(member, name_keyword):
                continue

            if title_keyword:
                member_title = str(member.get("title") or "").lower()
                if title_keyword not in member_title:
                    continue

            filtered.append(member)

        filtered.sort(
            key=lambda item: _build_sort_key(sort_by, item),
            reverse=(sort_order == "desc"),
        )

        total_filtered = len(filtered)
        paged = filtered[offset : offset + count]

        if not paged:
            return (
                f"【群成员筛选】群号: {group_id}\n"
                f"匹配总数: {total_filtered}，当前分页无数据（offset={offset}, count={count}）"
            )

        lines: list[str] = [f"【群成员筛选】群号: {group_id}"]
        lines.append(f"匹配总数: {total_filtered}，当前返回: {len(paged)}")
        if start_dt or end_dt:
            lines.append(
                f"入群时间范围: {format_datetime(start_dt)} ~ {format_datetime(end_dt)}"
            )
        lines.append(f"排序: {sort_by} {sort_order}")

        for index, member in enumerate(paged, start=offset + 1):
            user_id = member.get("user_id")
            level_value = parse_member_level(member.get("level"))
            level_text = str(level_value) if level_value is not None else "未知"
            role_text = role_to_cn(member.get("role"))
            join_text = format_timestamp(parse_unix_timestamp(member.get("join_time")))
            last_text = format_timestamp(
                parse_unix_timestamp(member.get("last_sent_time"))
            )
            lines.append(
                f"{index}. {member_display_name(member)} ({user_id}) [{role_text}] "
                f"Lv.{level_text} | 入群: {join_text} | 最后发言: {last_text}"
            )

        if offset + count < total_filtered:
            lines.append(
                f"... 还有 {total_filtered - (offset + count)} 人未显示，可增大 count 或调整 offset"
            )

        return "\n".join(lines)
    except Exception as exc:
        logger.exception(
            "筛选群成员失败: group=%s request_id=%s err=%s",
            group_id,
            request_id,
            exc,
        )
        return "筛选失败：群成员筛选服务暂时不可用，请稍后重试"
