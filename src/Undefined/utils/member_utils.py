"""成员处理工具函数"""

from datetime import datetime
from typing import Any, Dict
from collections import Counter


def filter_by_join_time(
    members: list[Dict[str, Any]], start_dt: datetime | None, end_dt: datetime | None
) -> list[Dict[str, Any]]:
    """按加群时间筛选成员

    参数:
        members: 成员列表
        start_dt: 开始时间
        end_dt: 结束时间

    返回:
        筛选后的成员列表
    """
    filtered: list[Dict[str, Any]] = []

    for member in members:
        join_time = member.get("join_time")
        if join_time is None:
            continue

        try:
            # 转换为 datetime
            if isinstance(join_time, (int, float)):
                join_dt = datetime.fromtimestamp(join_time)
            else:
                continue

            # 检查时间范围
            if start_dt and join_dt < start_dt:
                continue
            if end_dt and join_dt > end_dt:
                continue

            filtered.append(member)
        except (ValueError, OSError, OverflowError):
            continue

    return filtered


def analyze_join_trend(members: list[Dict[str, Any]]) -> Dict[str, Any]:
    """分析加群趋势

    参数:
        members: 成员列表

    返回:
        趋势分析字典
    """
    if not members:
        return {}

    # 按日期统计
    date_counter: Counter[str] = Counter()
    first_time: datetime | None = None
    last_time: datetime | None = None

    for member in members:
        join_time = member.get("join_time")
        if join_time is None:
            continue

        try:
            if isinstance(join_time, (int, float)):
                join_dt = datetime.fromtimestamp(join_time)
            else:
                continue

            date_str = join_dt.strftime("%Y-%m-%d")
            date_counter[date_str] += 1

            if first_time is None or join_dt < first_time:
                first_time = join_dt
            if last_time is None or join_dt > last_time:
                last_time = join_dt
        except (ValueError, OSError, OverflowError):
            continue

    # 计算平均每天加群人数
    total_days = len(date_counter)
    avg_per_day = len(members) / total_days if total_days > 0 else 0

    # 找出加群高峰日
    peak_date = ""
    peak_count = 0
    if date_counter:
        peak_date, peak_count = date_counter.most_common(1)[0]

    return {
        "avg_per_day": round(avg_per_day, 1),
        "peak_date": peak_date,
        "peak_count": peak_count,
        "first_time": first_time,
        "last_time": last_time,
        "daily_stats": dict(date_counter),
    }


def analyze_member_activity(
    members: list[Dict[str, Any]], message_counts: Dict[int, int], top_count: int
) -> Dict[str, Any]:
    """分析成员活跃度

    参数:
        members: 成员列表
        message_counts: 成员消息数量字典
        top_count: 显示最活跃成员的数量

    返回:
        活跃度分析字典
    """
    total_members = len(members)
    active_members = sum(1 for count in message_counts.values() if count > 0)
    inactive_members = total_members - active_members

    total_messages = sum(message_counts.values())
    avg_messages = total_messages / total_members if total_members > 0 else 0

    # 找出最活跃的成员
    sorted_members = sorted(message_counts.items(), key=lambda x: x[1], reverse=True)[
        :top_count
    ]

    # 获取成员详细信息
    member_map = {m.get("user_id"): m for m in members}
    top_members: list[Dict[str, Any]] = []

    for user_id, count in sorted_members:
        if count == 0:
            break
        member = member_map.get(user_id, {})
        nickname = member.get("card") or member.get("nickname", "未知")
        join_time = member.get("join_time")
        join_time_str = ""
        if join_time:
            try:
                if isinstance(join_time, (int, float)):
                    join_dt = datetime.fromtimestamp(join_time)
                    join_time_str = join_dt.strftime("%Y-%m-%d %H:%M:%S")
            except (ValueError, OSError, OverflowError):
                pass

        top_members.append(
            {
                "user_id": user_id,
                "nickname": nickname,
                "message_count": count,
                "join_time": join_time_str,
            }
        )

    return {
        "total_members": total_members,
        "active_members": active_members,
        "inactive_members": inactive_members,
        "active_rate": round(active_members / total_members * 100, 1)
        if total_members > 0
        else 0,
        "total_messages": total_messages,
        "avg_messages": round(avg_messages, 2),
        "top_members": top_members,
    }
