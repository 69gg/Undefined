from typing import Any, Dict
import logging

logger = logging.getLogger(__name__)


def _parse_positive_int(value: Any, field_name: str) -> tuple[int | None, str | None]:
    if value is None:
        return None, None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None, f"{field_name} 必须是整数"
    if parsed <= 0:
        return None, f"{field_name} 必须是正整数"
    return parsed, None


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    """向指定用户发送私聊消息"""
    request_id = str(context.get("request_id", "-"))
    user_id_raw = args.get("user_id")
    if user_id_raw is None:
        user_id_raw = context.get("user_id")

    user_id, user_error = _parse_positive_int(user_id_raw, "user_id")
    message = str(args.get("message", ""))

    if user_error:
        return f"发送失败：{user_error}"
    if user_id is None:
        return "目标用户 QQ 号不能为空"
    if not message:
        return "消息内容不能为空"

    runtime_config = context.get("runtime_config")
    if runtime_config is not None:
        if not runtime_config.is_private_allowed(user_id):
            return f"发送失败：目标用户 {user_id} 不在允许列表内（access.allowed_private_ids），已被访问控制拦截"

    send_private_message_callback = context.get("send_private_message_callback")
    sender = context.get("sender")

    if sender:
        try:
            await sender.send_private_message(user_id, message)
            return f"私聊消息已发送给用户 {user_id}"
        except Exception as e:
            logger.exception(
                "[私聊发送] sender 发送失败: user=%s request_id=%s err=%s",
                user_id,
                request_id,
                e,
            )
            return "发送失败：消息服务暂时不可用，请稍后重试"

    if send_private_message_callback:
        try:
            await send_private_message_callback(user_id, message)
            return f"私聊消息已发送给用户 {user_id}"
        except Exception as e:
            logger.exception(
                "[私聊发送] callback 发送失败: user=%s request_id=%s err=%s",
                user_id,
                request_id,
                e,
            )
            return "发送失败：消息服务暂时不可用，请稍后重试"

    logger.error("[私聊发送] 发送通道未设置: request_id=%s", request_id)
    return "私聊发送回调未设置"
