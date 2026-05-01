"""新成员活跃度分析工具"""

import logging
from typing import Any, Dict

from Undefined.utils.time_utils import parse_time_range, format_datetime
from Undefined.utils.member_utils import filter_by_join_time, analyze_member_activity
from Undefined.utils.message_utils import fetch_group_messages, count_messages_by_user

logger = logging.getLogger(__name__)


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    """分析新成员的活跃情况"""
    request_id = str(context.get("request_id", "-"))
    group_id = args.get("group_id") or context.get("group_id")
    join_start_time = args.get("join_start_time")
    join_end_time = args.get("join_end_time")

    # 1. 参数验证
    if not group_id:
        return "请提供群号（group_id 参数），或者在群聊中调用"

    try:
        group_id = int(group_id)
    except (ValueError, TypeError):
        return "参数类型错误：group_id 必须是整数"

    # 验证和规范化数值参数
    try:
        max_history_count_raw = args.get("max_history_count", 2000)
        max_history_count = (
            int(max_history_count_raw) if max_history_count_raw is not None else 2000
        )
        if max_history_count < 0:
            return "参数错误：max_history_count 必须是非负整数"
        cfg = context.get("runtime_config")
        fetch_cap = getattr(cfg, "history_search_scan_limit", 10000) if cfg else 10000
        max_history_count = min(max_history_count, fetch_cap)
    except (ValueError, TypeError):
        return "参数类型错误：max_history_count 必须是整数"

    try:
        top_count_raw = args.get("top_count", 5)
        top_count = int(top_count_raw) if top_count_raw is not None else 5
        if top_count < 0:
            return "参数错误：top_count 必须是非负整数"
        top_count = min(top_count, 20)
    except (ValueError, TypeError):
        return "参数类型错误：top_count 必须是整数"

    # 2. 解析时间范围
    start_dt, end_dt = parse_time_range(join_start_time, join_end_time)

    # 验证时间格式
    if join_start_time and start_dt is None:
        return "加群开始时间格式错误，请使用格式：YYYY-MM-DD HH:MM:SS，例如：2024-02-01 00:00:00"
    if join_end_time and end_dt is None:
        return "加群结束时间格式错误，请使用格式：YYYY-MM-DD HH:MM:SS，例如：2024-02-10 23:59:59"

    onebot_client = context.get("onebot_client")
    if not onebot_client:
        return "新成员活跃度分析功能不可用（OneBot 客户端未设置）"

    try:
        # 3. 获取群成员列表
        logger.info(f"开始获取群 {group_id} 的成员列表")
        member_list = await onebot_client.get_group_member_list(group_id)
        logger.info(f"获取到 {len(member_list)} 个成员")

        if not member_list:
            return f"群 {group_id} 没有成员数据"

        # 4. 筛选新成员
        new_members = filter_by_join_time(member_list, start_dt, end_dt)

        if not new_members:
            time_range_str = ""
            if start_dt or end_dt:
                time_range_str = f"在时间范围 {format_datetime(start_dt)} ~ {format_datetime(end_dt)} 内"
            return f"{time_range_str}没有新成员加群"

        # 5. 获取群消息历史
        logger.info(f"开始获取群 {group_id} 的消息历史，最多 {max_history_count} 条")
        all_messages = await fetch_group_messages(
            onebot_client, group_id, max_history_count, start_dt
        )
        logger.info(f"获取到 {len(all_messages)} 条历史消息")

        # 6. 统计每个新成员的发言情况
        member_ids: set[int] = set()
        for m in new_members:
            user_id = m.get("user_id")
            if user_id is not None and isinstance(user_id, int):
                member_ids.add(user_id)
        member_message_counts = count_messages_by_user(all_messages, member_ids)

        # 7. 分析活跃度
        activity_stats = analyze_member_activity(
            new_members, member_message_counts, top_count
        )

        # 8. 格式化返回
        result_parts = ["【新成员活跃度分析】"]
        result_parts.append(f"群号: {group_id}")

        if start_dt or end_dt:
            result_parts.append(
                f"加群时间范围: {format_datetime(start_dt)} ~ {format_datetime(end_dt)}"
            )

        result_parts.append("")
        result_parts.append("━━━━━━━━━━━━")
        result_parts.append("📊 活跃度统计")
        result_parts.append(f"新成员总数: {activity_stats.get('total_members', 0)} 人")
        result_parts.append(
            f"活跃成员: {activity_stats.get('active_members', 0)} 人 "
            f"({activity_stats.get('active_rate', 0)}%)"
        )
        result_parts.append(
            f"未发言成员: {activity_stats.get('inactive_members', 0)} 人 "
            f"({100 - activity_stats.get('active_rate', 0):.1f}%)"
        )

        result_parts.append("")
        result_parts.append(f"总发言数: {activity_stats.get('total_messages', 0)} 条")
        result_parts.append(f"人均发言: {activity_stats.get('avg_messages', 0)} 条")

        # 显示最活跃成员
        top_members = activity_stats.get("top_members", [])
        if top_members:
            result_parts.append("")
            result_parts.append("━━━━━━━━━━━━")
            result_parts.append(f"🔥 最活跃新成员 Top {len(top_members)}")

            for i, member in enumerate(top_members, 1):
                nickname = member.get("nickname", "未知")
                user_id = member.get("user_id", 0)
                message_count = member.get("message_count", 0)
                join_time = member.get("join_time", "")

                result_parts.append(
                    f"{i}. {nickname} ({user_id}) - {message_count} 条消息"
                )
                if join_time:
                    result_parts.append(f"   加群时间: {join_time}")
                result_parts.append("")

        return "\n".join(result_parts)

    except Exception as e:
        logger.exception(
            "分析新成员活跃度失败: group=%s request_id=%s err=%s",
            group_id,
            request_id,
            e,
        )
        return f"分析失败：{str(e)}"
