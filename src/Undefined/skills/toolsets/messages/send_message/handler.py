from typing import Any, Dict
import logging

from Undefined.attachments import (
    dispatch_pending_file_sends,
    render_message_with_pic_placeholders,
    scope_from_context,
)
from Undefined.utils.message_targets import TargetType, parse_positive_int
from Undefined.utils.message_targets import resolve_message_target

logger = logging.getLogger(__name__)


def _resolve_target(
    args: Dict[str, Any], context: Dict[str, Any]
) -> tuple[tuple[TargetType, int] | None, str | None]:
    return resolve_message_target(args, context)


def _is_current_group_target(context: Dict[str, Any], target_id: int) -> bool:
    context_group_id, _ = parse_positive_int(context.get("group_id"), "group_id")
    return context_group_id == target_id


def _is_current_private_target(context: Dict[str, Any], target_id: int) -> bool:
    context_user_id, _ = parse_positive_int(context.get("user_id"), "user_id")
    return context_user_id == target_id


def _get_context_group_id(context: Dict[str, Any]) -> int | None:
    group_id, _ = parse_positive_int(context.get("group_id"), "group_id")
    return group_id


def _group_access_error(runtime_config: Any, target_id: int) -> str:
    reason_getter = getattr(runtime_config, "group_access_denied_reason", None)
    reason = reason_getter(target_id) if callable(reason_getter) else None
    if reason == "blacklist":
        return (
            f"发送失败：目标群 {target_id} 在黑名单内（access.blocked_group_ids），"
            "已被访问控制拦截"
        )
    return (
        f"发送失败：目标群 {target_id} 不在允许列表内（access.allowed_group_ids），"
        "已被访问控制拦截"
    )


def _private_access_error(runtime_config: Any, target_id: int) -> str:
    reason_getter = getattr(runtime_config, "private_access_denied_reason", None)
    reason = reason_getter(target_id) if callable(reason_getter) else None
    if reason == "blacklist":
        return (
            f"发送失败：目标用户 {target_id} 在黑名单内（access.blocked_private_ids），"
            "已被访问控制拦截"
        )
    return (
        f"发送失败：目标用户 {target_id} 不在允许列表内（access.allowed_private_ids），"
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


def _format_send_success(message_id: Any) -> str:
    resolved_message_id = _normalize_message_id(message_id)
    if resolved_message_id is not None:
        return f"消息已发送（message_id={resolved_message_id}）"
    return "消息已发送"


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    """发送消息，支持群聊/私聊与 CQ 码格式"""
    request_id = str(context.get("request_id", "-"))
    message = str(args.get("message", ""))
    if not message:
        logger.warning("[发送消息] 收到空消息请求")
        return "消息内容不能为空"

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
            "[发送消息] 图片内嵌渲染失败: request_id=%s err=%s", request_id, exc
        )
        return f"发送失败：{exc}"
    message = rendered.delivery_text
    history_message = rendered.history_text
    history_attachments = list(rendered.attachments)

    # 解析 reply_to 参数（无效值静默忽略，视为未传）
    reply_to_id, _ = parse_positive_int(args.get("reply_to"), "reply_to")

    runtime_config = context.get("runtime_config")

    send_message_callback = context.get("send_message_callback")
    send_private_message_callback = context.get("send_private_message_callback")
    sender = context.get("sender")

    target, target_error = _resolve_target(args, context)
    if target_error or target is None:
        logger.warning(
            "[发送消息] 目标解析失败: request_id=%s err=%s", request_id, target_error
        )
        return f"发送失败：{target_error or '目标参数错误'}"

    target_type, target_id = target
    logger.debug(
        "[发送消息] request_id=%s target_type=%s target_id=%s",
        request_id,
        target_type,
        target_id,
    )

    if runtime_config is not None:
        if target_type == "group" and not runtime_config.is_group_allowed(target_id):
            return _group_access_error(runtime_config, target_id)
        if target_type == "private" and not runtime_config.is_private_allowed(
            target_id
        ):
            return _private_access_error(runtime_config, target_id)

    if sender:
        try:
            if target_type == "group":
                logger.info("[发送消息] 准备发送到群 %s: %s", target_id, message[:100])
                send_kwargs: dict[str, Any] = {
                    "reply_to": reply_to_id,
                    "history_message": history_message,
                }
                if history_attachments:
                    send_kwargs["attachments"] = history_attachments
                sent_message_id = await sender.send_group_message(
                    target_id,
                    message,
                    **send_kwargs,
                )
            else:
                logger.info("[发送消息] 准备发送私聊 %s: %s", target_id, message[:100])
                send_kwargs = {
                    "reply_to": reply_to_id,
                    "preferred_temp_group_id": _get_context_group_id(context),
                    "history_message": history_message,
                }
                if history_attachments:
                    send_kwargs["attachments"] = history_attachments
                sent_message_id = await sender.send_private_message(
                    target_id,
                    message,
                    **send_kwargs,
                )
            context["message_sent_this_turn"] = True
            await dispatch_pending_file_sends(
                rendered,
                sender=sender,
                target_type=target_type,
                target_id=target_id,
            )
            return _format_send_success(sent_message_id)
        except Exception as e:
            logger.exception(
                "[发送消息] 发送失败: target_type=%s target_id=%s request_id=%s err=%s",
                target_type,
                target_id,
                request_id,
                e,
            )
            return "发送失败：消息服务暂时不可用，请稍后重试"

    # 无 sender 时只做兼容回调；仅允许发送到"当前会话"避免误投递
    if target_type == "group":
        if send_message_callback and _is_current_group_target(context, target_id):
            try:
                await send_message_callback(message, reply_to=reply_to_id)
                context["message_sent_this_turn"] = True
                return "消息已发送"
            except Exception as e:
                logger.exception(
                    "[发送消息] 群聊回调发送失败: group=%s request_id=%s err=%s",
                    target_id,
                    request_id,
                    e,
                )
                return "发送失败：消息服务暂时不可用，请稍后重试"

        logger.error(
            "[发送消息] 无 sender，且群聊目标不匹配当前会话: target=%s request_id=%s",
            target_id,
            request_id,
        )
        return "发送失败：当前环境无法发送到目标群聊"

    if send_private_message_callback:
        try:
            await send_private_message_callback(
                target_id, message, reply_to=reply_to_id
            )
            context["message_sent_this_turn"] = True
            return "消息已发送"
        except Exception as e:
            logger.exception(
                "[发送消息] 私聊回调发送失败: user=%s request_id=%s err=%s",
                target_id,
                request_id,
                e,
            )
            return "发送失败：消息服务暂时不可用，请稍后重试"

    if send_message_callback and _is_current_private_target(context, target_id):
        try:
            await send_message_callback(message, reply_to=reply_to_id)
            context["message_sent_this_turn"] = True
            return "消息已发送"
        except Exception as e:
            logger.exception(
                "[发送消息] 兼容回调发送私聊失败: user=%s request_id=%s err=%s",
                target_id,
                request_id,
                e,
            )
            return "发送失败：消息服务暂时不可用，请稍后重试"

    logger.error(
        "[发送消息] 发送失败：缺少可用私聊发送通道 request_id=%s target=%s",
        request_id,
        target_id,
    )
    return "发送失败：当前环境无法发送到目标私聊"
