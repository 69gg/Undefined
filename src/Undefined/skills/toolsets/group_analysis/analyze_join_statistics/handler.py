"""加群统计分析工具"""

import logging
from typing import Any, Dict
from datetime import datetime

from Undefined.utils.time_utils import parse_time_range, format_datetime
from Undefined.utils.member_utils import filter_by_join_time, analyze_join_trend

logger = logging.getLogger(__name__)


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    """分析群的加群情况"""
    request_id = str(context.get("request_id", "-"))
    group_id = args.get("group_id") or context.get("group_id")
    start_time = args.get("start_time")
    end_time = args.get("end_time")
    include_trend = args.get("include_trend", True)
    include_member_list = args.get("include_member_list", False)

    # 1. 参数验证
    if not group_id:
        return "请提供群号（group_id 参数），或者在群聊中调用"

    try:
        group_id = int(group_id)
    except (ValueError, TypeError):
        return "参数类型错误：group_id 必须是整数"

    # 验证和规范化数值参数
    try:
        member_limit_raw = args.get("member_limit", 20)
        member_limit = int(member_limit_raw) if member_limit_raw is not None else 20
        if member_limit < 0:
            return "参数错误：member_limit 必须是非负整数"
        cfg = context.get("runtime_config")
        analysis_cap = getattr(cfg, "history_group_analysis_limit", 500) if cfg else 500
        member_limit = min(member_limit, analysis_cap)
    except (ValueError, TypeError):
        return "参数类型错误：member_limit 必须是整数"

    # 2. 解析时间范围
    start_dt, end_dt = parse_time_range(start_time, end_time)

    # 验证时间格式
    if start_time and start_dt is None:
        return "开始时间格式错误，请使用格式：YYYY-MM-DD HH:MM:SS，例如：2024-02-01 00:00:00"
    if end_time and end_dt is None:
        return "结束时间格式错误，请使用格式：YYYY-MM-DD HH:MM:SS，例如：2024-02-10 23:59:59"

    onebot_client = context.get("onebot_client")
    if not onebot_client:
        return "加群统计功能不可用（OneBot 客户端未设置）"

    try:
        # 3. 获取群成员列表
        logger.info(f"开始获取群 {group_id} 的成员列表")
        member_list = await onebot_client.get_group_member_list(group_id)
        logger.info(f"获取到 {len(member_list)} 个成员")

        if not member_list:
            return f"群 {group_id} 没有成员数据"

        # 4. 按加群时间筛选
        filtered_members = filter_by_join_time(member_list, start_dt, end_dt)

        if not filtered_members:
            time_range_str = ""
            if start_dt or end_dt:
                time_range_str = f"在时间范围 {format_datetime(start_dt)} ~ {format_datetime(end_dt)} 内"
            return f"{time_range_str}没有成员加群"

        # 5. 格式化返回
        result_parts = ["【加群统计分析】"]
        result_parts.append(f"群号: {group_id}")

        if start_dt or end_dt:
            result_parts.append(
                f"时间范围: {format_datetime(start_dt)} ~ {format_datetime(end_dt)}"
            )

        result_parts.append("")
        result_parts.append("━━━━━━━━━━━━")
        result_parts.append("📊 加群统计")
        result_parts.append(f"总人数: {len(filtered_members)} 人")

        # 找出首次和最后加群时间
        join_times = []
        for member in filtered_members:
            join_time = member.get("join_time")
            if join_time:
                try:
                    if isinstance(join_time, (int, float)):
                        join_dt = datetime.fromtimestamp(join_time)
                        join_times.append(join_dt)
                except (ValueError, OSError, OverflowError):
                    pass

        if join_times:
            first_join = min(join_times)
            last_join = max(join_times)
            result_parts.append(f"首次加群: {first_join.strftime('%Y-%m-%d %H:%M:%S')}")
            result_parts.append(f"最后加群: {last_join.strftime('%Y-%m-%d %H:%M:%S')}")

        # 6. 可选：趋势分析
        if include_trend:
            trend_stats = analyze_join_trend(filtered_members)
            if trend_stats:
                result_parts.append("")
                result_parts.append("━━━━━━━━━━━━")
                result_parts.append("📈 加群趋势")
                result_parts.append(
                    f"  • 平均每天: {trend_stats.get('avg_per_day', 0)} 人"
                )

                peak_date = trend_stats.get("peak_date")
                peak_count = trend_stats.get("peak_count", 0)
                if peak_date:
                    result_parts.append(
                        f"  • 加群高峰日: {peak_date} ({peak_count} 人)"
                    )

                daily_stats = trend_stats.get("daily_stats", {})
                if daily_stats:
                    result_parts.append("")
                    result_parts.append("每日加群人数:")
                    # 按日期排序
                    sorted_dates = sorted(daily_stats.items())
                    for date_str, count in sorted_dates:
                        # 使用简单的条形图
                        bar = "█" * min(count, 20)
                        result_parts.append(f"  {date_str}: {bar} {count} 人")

        # 7. 可选：成员列表
        if include_member_list:
            result_parts.append("")
            result_parts.append(
                f"新成员列表 (显示前 {min(member_limit, len(filtered_members))} 人)"
            )

            # 按加群时间排序
            sorted_members = sorted(
                filtered_members, key=lambda m: m.get("join_time", 0)
            )

            for i, member in enumerate(sorted_members[:member_limit], 1):
                nickname = member.get("card") or member.get("nickname", "未知")
                user_id = member.get("user_id", 0)
                join_time = member.get("join_time")
                join_time_str = ""
                if join_time:
                    try:
                        if isinstance(join_time, (int, float)):
                            join_dt = datetime.fromtimestamp(join_time)
                            join_time_str = join_dt.strftime("%Y-%m-%d %H:%M:%S")
                    except (ValueError, OSError, OverflowError):
                        pass

                result_parts.append(
                    f"{i}. {nickname} ({user_id}) - 加群: {join_time_str}"
                )

        return "\n".join(result_parts)

    except Exception as e:
        logger.exception(
            "分析加群统计失败: group=%s request_id=%s err=%s",
            group_id,
            request_id,
            e,
        )
        return f"分析失败：{str(e)}"
