from typing import Any, Dict
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    group_id = args.get("group_id")
    if not group_id:
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
            return "当前群聊暂无公告"

        lines = [f"群 {group_id} 公告列表："]
        for i, notice in enumerate(notices[:5]):  # 最多显示 5 条
            # 公告字段可能因实现不同而异，通常包含 content, sender_id, pub_time 等
            content = notice.get("content", notice.get("text", "无内容"))
            sender_id = notice.get("sender_id", notice.get("uin", "未知"))
            pub_time_ts = notice.get("pub_time", notice.get("time", 0))

            pub_time = "未知时间"
            if pub_time_ts:
                pub_time = datetime.fromtimestamp(pub_time_ts).strftime(
                    "%Y-%m-%d %H:%M:%S"
                )

            lines.append(f"{i + 1}. [{pub_time}] 发布者({sender_id}):\n{content}")
            lines.append("-" * 20)

        return "\n".join(lines)
    except Exception as e:
        logger.error(f"[群公告] 获取群 {group_id} 公告失败: {e}")
        return f"获取群公告失败: {e}"
