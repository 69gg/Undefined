from typing import Any, Dict
import logging

logger = logging.getLogger(__name__)


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    message = args.get("message", "")
    if not message:
        logger.warning("[发送消息] 收到空消息请求")
        return "消息内容不能为空"

    # 如果可用，使用 context.recent_replies 检查重复
    recent_replies = context.get("recent_replies")
    if recent_replies is not None and message in recent_replies:
        logger.info(f"[发送消息] 检测到重复消息内容: {message[:50]}...")

    at_user = args.get("at_user")
    send_message_callback = context.get("send_message_callback")
    sender = context.get("sender")

    # 优先使用 sender 接口
    if sender:
        # 优先从 context 获取 group_id（避免并发竞态条件）
        group_id = context.get("group_id")
        if group_id:
            logger.debug(f"[发送消息] 从 context 获取 group_id: {group_id}")
        else:
            # 向后兼容：从 ai_client 获取（已废弃）
            ai_client = context.get("ai_client")
            group_id = ai_client.current_group_id if ai_client else None
            if group_id:
                logger.warning(
                    f"[发送消息] 从 ai_client.current_group_id 获取群号（已废弃，可能存在并发问题）: {group_id}"
                )

        if group_id:
            logger.info(f"[发送消息] 准备发送到群 {group_id}: {message[:100]}")
            if at_user:
                logger.debug(f"[发送消息] 同时 @ 用户: {at_user}")
                message = f"[CQ:at,qq={at_user}] {message}"
            try:
                await sender.send_group_message(group_id, message)
                if recent_replies is not None:
                    recent_replies.append(message)
                return "消息已发送"
            except Exception as e:
                logger.exception(f"[发送消息] 发送到群 {group_id} 失败: {e}")
                return f"发送失败: {e}"
        elif send_message_callback:
            logger.info(f"[发送消息] 无法确定群ID，尝试使用回调发送: {message[:100]}")
            await send_message_callback(message, at_user)
            if recent_replies is not None:
                recent_replies.append(message)
            return "消息已发送"
        else:
            logger.error("[发送消息] 发送失败：无法确定群组 ID 且无回调可用")
            return "发送失败：无法确定群组 ID"

    elif send_message_callback:
        logger.info(f"[发送消息] 使用回调发送私聊或默认消息: {message[:100]}")
        await send_message_callback(message, at_user)
        if recent_replies is not None:
            recent_replies.append(message)
        return "消息已发送"
    else:
        logger.error("[发送消息] 发送消息回调和 sender 均未设置")
        return "发送消息回调未设置"
