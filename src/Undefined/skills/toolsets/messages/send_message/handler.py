from typing import Any, Dict
import logging

logger = logging.getLogger(__name__)


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    """发送群聊消息，支持文本和 CQ 码格式"""
    request_id = str(context.get("request_id", "-"))
    message = args.get("message", "")
    if not message:
        logger.warning("[发送消息] 收到空消息请求")
        return "消息内容不能为空"

    runtime_config = context.get("runtime_config")

    # 如果可用，使用 context.recent_replies 检查重复
    recent_replies = context.get("recent_replies")
    if recent_replies is not None and message in recent_replies:
        logger.info(f"[发送消息] 检测到重复消息内容: {message[:50]}...")

    at_user = args.get("at_user")
    send_message_callback = context.get("send_message_callback")
    sender = context.get("sender")

    # 仅使用当前请求上下文中的 group_id，避免共享状态导致并发串话。
    group_id = args.get("group_id")
    if group_id is None:
        group_id = context.get("group_id")

    # 优先使用 sender 接口
    if sender:
        if group_id is not None:
            try:
                group_id_int = int(group_id)
            except (TypeError, ValueError):
                logger.warning("[发送消息] 非法 group_id: %s", group_id)
                return "发送失败：group_id 必须是整数"

            logger.debug("[发送消息] 从请求上下文获取 group_id: %s", group_id)
            if runtime_config is not None and not runtime_config.is_group_allowed(
                group_id_int
            ):
                return f"发送失败：目标群 {group_id_int} 不在允许列表内（access.allowed_group_ids），已被访问控制拦截"
            logger.info(f"[发送消息] 准备发送到群 {group_id_int}: {message[:100]}")
            if at_user:
                logger.debug(f"[发送消息] 同时 @ 用户: {at_user}")
                message = f"[CQ:at,qq={at_user}] {message}"
            try:
                await sender.send_group_message(group_id_int, message)
                if recent_replies is not None:
                    recent_replies.append(message)
                return "消息已发送"
            except Exception as e:
                logger.exception(
                    "[发送消息] 发送到群失败: group=%s request_id=%s err=%s",
                    group_id_int,
                    request_id,
                    e,
                )
                return "发送失败：消息服务暂时不可用，请稍后重试"
        elif send_message_callback:
            # 兼容：当无法确定群ID时，回调可能用于私聊回复
            if runtime_config is not None:
                uid = context.get("user_id")
                if (
                    isinstance(uid, int)
                    and uid > 0
                    and not runtime_config.is_private_allowed(uid)
                ):
                    return f"发送失败：目标用户 {uid} 不在允许列表内（access.allowed_private_ids），已被访问控制拦截"
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
