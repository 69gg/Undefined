from typing import Any, Dict
import logging

logger = logging.getLogger(__name__)


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    request_id = str(context.get("request_id", "-"))
    group_id = args.get("group_id") or context.get("group_id")

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
        logger.exception(
            "[群打卡] 打卡失败: group=%s request_id=%s err=%s",
            group_id,
            request_id,
            e,
        )
        return "打卡失败：服务暂时不可用，请稍后重试"
