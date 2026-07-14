from typing import Any, Dict
import logging

from Undefined.attachments import (
    dispatch_pending_file_sends,
    render_message_with_pic_placeholders,
    scope_from_context,
)
from Undefined.skills.toolsets.messages.context_utils import mark_message_sent
from Undefined.utils.message_targets import (
    parse_delivery_address,
    resolve_delivery_address,
)

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


def _private_access_error(runtime_config: Any, user_id: int) -> str:
    reason_getter = getattr(runtime_config, "private_access_denied_reason", None)
    reason = reason_getter(user_id) if callable(reason_getter) else None
    if reason == "blacklist":
        return (
            f"发送失败：目标用户 {user_id} 在黑名单内（access.blocked_private_ids），"
            "已被访问控制拦截"
        )
    return (
        f"发送失败：目标用户 {user_id} 不在允许列表内（access.allowed_private_ids），"
        "已被访问控制拦截"
    )


def _normalize_message_id(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, str):
        text = value.strip()
        if text.isdigit():
            parsed = int(text)
            return parsed if parsed > 0 else None
    return None


def _format_send_success(user_id: int, message_id: Any) -> str:
    resolved_message_id = _normalize_message_id(message_id)
    if resolved_message_id is not None:
        return f"私聊消息已发送给用户 {user_id}（message_id={resolved_message_id}）"
    return f"私聊消息已发送给用户 {user_id}"


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    """向指定用户发送私聊消息"""
    request_id = str(context.get("request_id", "-"))
    target, target_error = resolve_delivery_address(args, context)
    if target_error or target is None:
        return f"发送失败：{target_error or '无法确定目标私聊'}"
    if target.target_type != "private":
        return "发送失败：send_private_message 不支持群聊地址"
    user_id = target.target_id
    message = str(args.get("message", ""))

    # 解析 reply_to 参数（无效值静默忽略，视为未传）
    reply_to_id, _ = _parse_positive_int(args.get("reply_to"), "reply_to")

    if not message:
        return "消息内容不能为空"
    if target.channel == "wechat" and reply_to_id is not None:
        return "发送失败：微信 iLink 暂不支持引用回复（reply_to）"

    attachment_registry = context.get("attachment_registry")
    scope_key = scope_from_context(context)
    try:
        rendered = await render_message_with_pic_placeholders(
            message,
            registry=attachment_registry,
            scope_key=scope_key,
            strict=True,
        )
    except Exception as exc:
        logger.warning(
            "[私聊发送] 图片内嵌渲染失败: request_id=%s err=%s", request_id, exc
        )
        return f"发送失败：{exc}"
    message = rendered.delivery_text
    history_message = rendered.history_text
    history_attachments = list(rendered.attachments)

    runtime_config = context.get("runtime_config")
    if runtime_config is not None:
        if not runtime_config.is_private_allowed(user_id):
            return _private_access_error(runtime_config, user_id)

    send_private_message_callback = context.get("send_private_message_callback")
    sender = context.get("sender")

    if sender:
        try:
            send_kwargs: dict[str, Any] = {
                "reply_to": reply_to_id,
                "history_message": history_message,
            }
            if history_attachments:
                send_kwargs["attachments"] = history_attachments
            send_address_message = getattr(sender, "send_address_message", None)
            if callable(send_address_message):
                sent_message_id = await send_address_message(
                    target,
                    message,
                    **send_kwargs,
                )
            elif target.channel == "qq":
                sent_message_id = await sender.send_private_message(
                    user_id,
                    message,
                    **send_kwargs,
                )
            else:
                raise RuntimeError("当前 sender 不支持微信投递地址")
            mark_message_sent(context)
            await dispatch_pending_file_sends(
                rendered,
                sender=sender,
                target_type="private",
                target_id=user_id,
                registry=attachment_registry,
                address=target,
            )
            return _format_send_success(user_id, sent_message_id)
        except Exception as e:
            logger.exception(
                "[私聊发送] sender 发送失败: user=%s request_id=%s err=%s",
                user_id,
                request_id,
                e,
            )
            return "发送失败：消息服务暂时不可用，请稍后重试"

    if send_private_message_callback and target.channel == "qq":
        try:
            await send_private_message_callback(user_id, message, reply_to=reply_to_id)
            mark_message_sent(context)
            return f"私聊消息已发送给用户 {user_id}"
        except Exception as e:
            logger.exception(
                "[私聊发送] callback 发送失败: user=%s request_id=%s err=%s",
                user_id,
                request_id,
                e,
            )
            return "发送失败：消息服务暂时不可用，请稍后重试"

    send_message_callback = context.get("send_message_callback")
    current_address, _ = parse_delivery_address(context.get("address"))
    if send_message_callback and current_address == target:
        try:
            await send_message_callback(message, reply_to=reply_to_id)
            mark_message_sent(context)
            return f"私聊消息已发送给用户 {user_id}"
        except Exception as exc:
            logger.exception(
                "[私聊发送] 当前会话回调失败: address=%s request_id=%s err=%s",
                target.canonical,
                request_id,
                exc,
            )
            return "发送失败：消息服务暂时不可用，请稍后重试"

    logger.error("[私聊发送] 发送通道未设置: request_id=%s", request_id)
    return "私聊发送回调未设置"
