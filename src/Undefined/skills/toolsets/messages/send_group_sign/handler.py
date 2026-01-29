from typing import Any, Dict
import logging

logger = logging.getLogger(__name__)


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    group_id = args.get("group_id") or context.get("group_id")
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
        result = await sender.onebot.send_group_sign(group_id)
        logger.info(f"[群打卡] 群 {group_id} 打卡结果: {result}")
        return "打卡成功"
    except Exception as e:
        logger.error(f"[群打卡] 群 {group_id} 打卡失败: {e}")
        return f"打卡失败: {e}"
