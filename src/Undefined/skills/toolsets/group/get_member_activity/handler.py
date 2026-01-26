import logging
import time
from datetime import datetime
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    """分析群成员活跃度"""
    ai_client = context.get("ai_client")
    group_id = args.get("group_id") or context.get("group_id")
    if not group_id:
        # 向后兼容
        ai_client = context.get("ai_client")
        group_id = ai_client.current_group_id if ai_client else None
    threshold_days = args.get("threshold_days", 30)
    display_count = args.get("count", 10)

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
        member_list = await onebot_client.get_group_member_list(group_id)

        if not member_list:
            return f"未能获取到群 {group_id} 的成员列表"

        now_ts = time.time()
        threshold_ts = now_ts - (threshold_days * 24 * 3600)

        active_members: List[Dict[str, Any]] = []
        inactive_members: List[Dict[str, Any]] = []

        for m in member_list:
            last_sent = m.get("last_sent_time", 0)
            if last_sent == 0:
                # 记录为从未发言（除非刚入群）
                inactive_members.append(m)
            elif last_sent < threshold_ts:
                inactive_members.append(m)
            else:
                active_members.append(m)

        # 排序：按最后发言时间
        active_members.sort(key=lambda x: x.get("last_sent_time", 0), reverse=True)
        inactive_members.sort(key=lambda x: x.get("last_sent_time", 0))

        result_parts = [f"【群活跃度统计】群号: {group_id}"]
        result_parts.append(f"总成员数: {len(member_list)}")
        result_parts.append(
            f"活跃成员 (最近{threshold_days}天内发言): {len(active_members)}"
        )
        result_parts.append(f"非活跃成员: {len(inactive_members)}")

        # 计算比例
        if len(member_list) > 0:
            active_rate = (len(active_members) / len(member_list)) * 100
            result_parts.append(f"活跃率: {active_rate:.1f}%")

        # 列出最活跃成员
        if active_members:
            result_parts.append(
                f"\n🔥 最活跃成员 (Top {min(display_count, len(active_members))}):"
            )
            for i, m in enumerate(active_members[:display_count], 1):
                name = m.get("card") or m.get("nickname") or str(m.get("user_id"))
                last_dt = datetime.fromtimestamp(m.get("last_sent_time", 0)).strftime(
                    "%Y-%m-%d %H:%M"
                )
                result_parts.append(f"{i}. {name} (最后发言: {last_dt})")

        # 列出长期潜水成员
        if inactive_members:
            result_parts.append(
                f"\n👻 潜水成员 (Top {min(display_count, len(inactive_members))}):"
            )
            for i, m in enumerate(inactive_members[:display_count], 1):
                name = m.get("card") or m.get("nickname") or str(m.get("user_id"))
                last_sent = m.get("last_sent_time", 0)
                if last_sent == 0:
                    last_desc = "从未发言"
                else:
                    last_desc = datetime.fromtimestamp(last_sent).strftime("%Y-%m-%d")
                result_parts.append(f"{i}. {name} (最后发言: {last_desc})")

        return "\n".join(result_parts)

    except Exception as e:
        logger.exception(f"获取群活跃度度失败: {e}")
        return f"获取失败：{str(e)}"
