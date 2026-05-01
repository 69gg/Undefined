"""成员消息分析工具"""

import logging
from typing import Any, Dict

from Undefined.utils.time_utils import parse_time_range, format_datetime
from Undefined.utils.message_utils import (
    fetch_group_messages,
    filter_user_messages,
    count_message_types,
    analyze_activity_pattern,
    format_messages,
)

logger = logging.getLogger(__name__)


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    """分析指定群成员的消息情况"""
    request_id = str(context.get("request_id", "-"))
    group_id = args.get("group_id") or context.get("group_id")
    user_id = args.get("user_id")
    start_time = args.get("start_time")
    end_time = args.get("end_time")
    include_messages = args.get("include_messages", False)

    # 1. 参数验证
    if not group_id:
        return "请提供群号（group_id 参数），或者在群聊中调用"
    if not user_id:
        return "请提供要分析的成员QQ号（user_id 参数）"

    try:
        group_id = int(group_id)
        user_id = int(user_id)
    except (ValueError, TypeError):
        return "参数类型错误：group_id 和 user_id 必须是整数"

    # 验证和规范化数值参数
    try:
        message_limit_raw = args.get("message_limit", 20)
        message_limit = int(message_limit_raw) if message_limit_raw is not None else 20
        if message_limit < 0:
            return "参数错误：message_limit 必须是非负整数"
        cfg = context.get("runtime_config")
        analysis_cap = getattr(cfg, "history_group_analysis_limit", 500) if cfg else 500
        message_limit = min(message_limit, analysis_cap)
    except (ValueError, TypeError):
        return "参数类型错误：message_limit 必须是整数"

    try:
        max_history_count_raw = args.get("max_history_count", 2000)
        max_history_count = (
            int(max_history_count_raw) if max_history_count_raw is not None else 2000
        )
        if max_history_count < 0:
            return "参数错误：max_history_count 必须是非负整数"
        fetch_cap = getattr(cfg, "history_search_scan_limit", 10000) if cfg else 10000
        max_history_count = min(max_history_count, fetch_cap)
    except (ValueError, TypeError):
        return "参数类型错误：max_history_count 必须是整数"

    # 2. 解析时间范围
    start_dt, end_dt = parse_time_range(start_time, end_time)

    # 验证时间格式
    if start_time and start_dt is None:
        return "开始时间格式错误，请使用格式：YYYY-MM-DD HH:MM:SS，例如：2024-02-01 00:00:00"
    if end_time and end_dt is None:
        return "结束时间格式错误，请使用格式：YYYY-MM-DD HH:MM:SS，例如：2024-02-10 23:59:59"

    onebot_client = context.get("onebot_client")
    if not onebot_client:
        return "消息分析功能不可用（OneBot 客户端未设置）"

    try:
        # 3. 获取群消息历史
        logger.info(f"开始获取群 {group_id} 的消息历史，最多 {max_history_count} 条")
        all_messages = await fetch_group_messages(
            onebot_client, group_id, max_history_count, start_dt
        )
        logger.info(f"获取到 {len(all_messages)} 条历史消息")

        # 4. 筛选目标用户的消息
        user_messages = filter_user_messages(all_messages, user_id, start_dt, end_dt)

        if not user_messages:
            time_range_str = ""
            if start_dt or end_dt:
                time_range_str = f"在时间范围 {format_datetime(start_dt)} ~ {format_datetime(end_dt)} 内"
            return f"成员 {user_id} {time_range_str}无消息记录"

        # 5. 统计分析
        total_count = len(user_messages)
        type_stats = count_message_types(user_messages)
        activity_stats = analyze_activity_pattern(user_messages)

        # 6. 获取成员信息
        member_info = await onebot_client.get_group_member_info(group_id, user_id)
        member_name = "未知"
        if member_info:
            member_name = member_info.get("card") or member_info.get("nickname", "未知")

        # 7. 格式化返回
        result_parts = ["【成员消息分析】"]
        result_parts.append(f"群号: {group_id}")
        result_parts.append(f"成员: {member_name} ({user_id})")

        if start_dt or end_dt:
            result_parts.append(
                f"时间范围: {format_datetime(start_dt)} ~ {format_datetime(end_dt)}"
            )

        result_parts.append("")
        result_parts.append("━━━━━━━━━━━━")
        result_parts.append("📊 消息统计")
        result_parts.append(f"总消息数: {total_count} 条")

        if type_stats:
            result_parts.append("")
            result_parts.append("消息类型分布:")
            for msg_type, count in sorted(
                type_stats.items(), key=lambda x: x[1], reverse=True
            ):
                percentage = count / total_count * 100
                result_parts.append(f"  • {msg_type}: {count} 条 ({percentage:.1f}%)")

        if activity_stats:
            result_parts.append("")
            result_parts.append("━━━━━━━━━━━━")
            result_parts.append("📈 活跃度分析")
            result_parts.append(
                f"  • 平均每天: {activity_stats.get('avg_per_day', 0)} 条消息"
            )
            result_parts.append(
                f"  • 最活跃时段: {activity_stats.get('most_active_hour', '未知')}"
            )
            result_parts.append(
                f"  • 最活跃日期: {activity_stats.get('most_active_weekday', '未知')}"
            )

            first_time = activity_stats.get("first_time")
            last_time = activity_stats.get("last_time")
            if first_time:
                result_parts.append(
                    f"  • 首次发言: {first_time.strftime('%Y-%m-%d %H:%M:%S')}"
                )
            if last_time:
                result_parts.append(
                    f"  • 最后发言: {last_time.strftime('%Y-%m-%d %H:%M:%S')}"
                )

        # 8. 可选：获取消息内容
        if include_messages:
            formatted_msgs = format_messages(user_messages[:message_limit])
            result_parts.append("")
            result_parts.append(f"最近消息内容 (显示最近 {len(formatted_msgs)} 条)")
            for msg in formatted_msgs:
                result_parts.append(
                    f'<message sender="{msg["sender"]}" sender_id="{msg["sender_id"]}" time="{msg["time"]}">'
                )
                result_parts.append(f"<content>{msg['content']}</content>")
                result_parts.append("</message>")
                result_parts.append("---")

        return "\n".join(result_parts)

    except Exception as e:
        logger.exception(
            "分析成员消息失败: group=%s user=%s request_id=%s err=%s",
            group_id,
            user_id,
            request_id,
            e,
        )
        return f"分析失败：{str(e)}"
