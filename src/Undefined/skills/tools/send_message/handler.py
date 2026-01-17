from typing import Any, Dict
import logging

logger = logging.getLogger(__name__)


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    message = args.get("message", "")
    if not message:
        return "消息内容不能为空"

    message = message.replace("\\", "")

    # 如果可用，使用 context.recent_replies 检查重复
    recent_replies = context.get("recent_replies")
    if recent_replies is not None and message in recent_replies:
        logger.info(f"发送了重复消息（已移除屏蔽）: {message[:50]}...")

    at_user = args.get("at_user")
    send_message_callback = context.get("send_message_callback")
    sender = context.get("sender")

    # 优先使用 sender 接口
    if sender:
        # ai.ask 已经确定了当前群组 ID (current_group_id)
        # 但 sender.send_group_message 需要 group_id
        # 这里 sender 本身并没有上下文，需要从 context 或 args 获取
        # ai.py 的 current_group_id 记录了相关信息
        # context 中的 ai_client.current_group_id 可用
        # ai_client 在 context 中。
        ai_client = context.get("ai_client")
        group_id = ai_client.current_group_id if ai_client else None

        if group_id:
            if at_user:
                message = f"[CQ:at,qq={at_user}] {message}"
            await sender.send_group_message(group_id, message)
            if recent_replies is not None:
                recent_replies.append(message)
            return "消息已发送"
        elif (
            send_message_callback
        ):  # 如果获取不到 group_id，尝试 callback (callback 闭包里可能有)
            await send_message_callback(message, at_user)
            if recent_replies is not None:
                recent_replies.append(message)
            return "消息已发送"
        else:
            return "发送失败：无法确定群组 ID"

    elif send_message_callback:
        await send_message_callback(message, at_user)
        if recent_replies is not None:
            recent_replies.append(message)
        return "消息已发送"
    else:
        return "发送消息回调未设置"
