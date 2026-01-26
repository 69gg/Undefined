from typing import Any, Dict
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    group_id = args.get("group_id")
    if not group_id:
        # 优先从 context 获取（避免并发问题）
        group_id = context.get("group_id")
    if not group_id:
        # 向后兼容
        ai_client = context.get("ai_client")
        group_id = ai_client.current_group_id if ai_client else None

    if not group_id:
        return "未能确定群聊 ID，请提供 group_id 参数或在群聊中调用"

    sender = context.get("sender")
    if not sender or not hasattr(sender, "onebot"):
        return "OneBot 客户端未连接"

    try:
        notices = await sender.onebot._get_group_notices(group_id)
        if not notices:
            return f"群 {group_id} 暂无公告记录"

        total_count = len(notices)

        # 查找最新的公告时间
        latest_ts = 0
        for notice in notices:
            ts = int(
                notice.get("pub_time")
                or notice.get("publish_time")
                or notice.get("time", 0)
            )
            if ts > latest_ts:
                latest_ts = ts

        latest_time_str = "未知"
        if latest_ts:
            latest_time_str = datetime.fromtimestamp(latest_ts).strftime(
                "%Y-%m-%d %H:%M:%S"
            )

        return f"群 {group_id} 公告统计：\n当前共有 {total_count} 条公告记录\n最后更新时间: {latest_time_str}"

    except Exception as e:
        logger.exception(f"[群公告] 获取群 {group_id} 公公告统计失败: {e}")
        return f"获取群公告统计失败: {e}"
