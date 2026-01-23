from typing import Any, Dict
import logging

logger = logging.getLogger(__name__)


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    user_id = args.get("user_id")
    message = args.get("message", "")

    if not user_id:
        return "目标用户 QQ 号不能为空"
    if not message:
        return "消息内容不能为空"

    message = message.replace("\\", "")

    recent_replies = context.get("recent_replies")
    if recent_replies is not None and message in recent_replies:
        logger.info(f"发送了重复私聊消息（已移除屏蔽）: {message[:50]}...")

    send_private_message_callback = context.get("send_private_message_callback")
    sender = context.get("sender")

    if sender:
        await sender.send_private_message(user_id, message)
        if recent_replies is not None:
            recent_replies.append(message)
        return f"私聊消息已发送给用户 {user_id}"
    elif send_private_message_callback:
        await send_private_message_callback(user_id, message)
        if recent_replies is not None:
            recent_replies.append(message)
        return f"私聊消息已发送给用户 {user_id}"
    else:
        return "私聊发送回调未设置"
