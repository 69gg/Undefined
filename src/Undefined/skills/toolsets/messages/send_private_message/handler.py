from typing import Any, Dict
import logging

logger = logging.getLogger(__name__)


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    """向指定用户发送私聊消息"""
    user_id = args.get("user_id")
    message = args.get("message", "")

    if not user_id:
        return "目标用户 QQ 号不能为空"
    if not message:
        return "消息内容不能为空"

    runtime_config = context.get("runtime_config")
    if runtime_config is not None:
        try:
            uid = int(user_id)
        except Exception:
            uid = 0
        if uid > 0 and not runtime_config.is_private_allowed(uid):
            return f"发送失败：目标用户 {uid} 不在允许列表内（access.allowed_private_ids），已被访问控制拦截"

    message = message.replace("\\", "")

    send_private_message_callback = context.get("send_private_message_callback")
    sender = context.get("sender")

    if sender:
        await sender.send_private_message(user_id, message)
        return f"私聊消息已发送给用户 {user_id}"
    elif send_private_message_callback:
        await send_private_message_callback(user_id, message)
        return f"私聊消息已发送给用户 {user_id}"
    else:
        return "私聊发送回调未设置"
