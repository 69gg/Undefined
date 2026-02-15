from typing import Any, Dict, Literal
import logging

logger = logging.getLogger(__name__)


TargetType = Literal["group", "private"]


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


def _resolve_target(
    args: Dict[str, Any], context: Dict[str, Any]
) -> tuple[tuple[TargetType, int] | None, str | None]:
    target_type_raw = args.get("target_type")
    target_id_raw = args.get("target_id")
    has_target_type = target_type_raw is not None
    has_target_id = target_id_raw is not None

    # 显式目标优先：target_type + target_id
    if has_target_type or has_target_id:
        if not has_target_type and has_target_id:
            return None, "target_type 与 target_id 必须同时提供"

        if not isinstance(target_type_raw, str):
            return None, "target_type 必须是字符串（group 或 private）"
        target_type = target_type_raw.strip().lower()
        if target_type not in ("group", "private"):
            return None, "target_type 只能是 group 或 private"

        normalized_target_type: TargetType = (
            "group" if target_type == "group" else "private"
        )

        if has_target_id:
            target_id, id_error = _parse_positive_int(target_id_raw, "target_id")
            if id_error or target_id is None:
                return None, id_error or "target_id 非法"
            return (normalized_target_type, target_id), None

        request_type = context.get("request_type")
        if request_type != normalized_target_type:
            return None, "target_type 与当前会话类型不一致，无法推断 target_id"

        if normalized_target_type == "group":
            group_id, group_error = _parse_positive_int(
                context.get("group_id"), "group_id"
            )
            if group_error or group_id is None:
                return None, group_error or "无法根据 target_type 推断 target_id"
            logger.info(
                "[发送消息] 推断目标: request_id=%s target_type=%s target_id=%s",
                context.get("request_id", "-"),
                normalized_target_type,
                group_id,
            )
            return ("group", group_id), None

        user_id, user_error = _parse_positive_int(context.get("user_id"), "user_id")
        if user_error or user_id is None:
            return None, user_error or "无法根据 target_type 推断 target_id"
        logger.info(
            "[发送消息] 推断目标: request_id=%s target_type=%s target_id=%s",
            context.get("request_id", "-"),
            normalized_target_type,
            user_id,
        )
        return ("private", user_id), None

    # 兼容旧参数：group_id / user_id
    legacy_group_id = args.get("group_id")
    if legacy_group_id is not None:
        group_id, group_error = _parse_positive_int(legacy_group_id, "group_id")
        if group_error or group_id is None:
            return None, group_error or "group_id 非法"
        return ("group", group_id), None

    legacy_user_id = args.get("user_id")
    if legacy_user_id is not None:
        user_id, user_error = _parse_positive_int(legacy_user_id, "user_id")
        if user_error or user_id is None:
            return None, user_error or "user_id 非法"
        return ("private", user_id), None

    # 自动回落：优先按 request_type 决定当前会话
    request_type = context.get("request_type")
    if request_type == "group":
        group_id, group_error = _parse_positive_int(context.get("group_id"), "group_id")
        if group_error:
            return None, group_error
        if group_id is not None:
            return ("group", group_id), None
    elif request_type == "private":
        user_id, user_error = _parse_positive_int(context.get("user_id"), "user_id")
        if user_error:
            return None, user_error
        if user_id is not None:
            return ("private", user_id), None

    # 最后兜底（兼容旧上下文）
    fallback_group_id, fallback_group_error = _parse_positive_int(
        context.get("group_id"), "group_id"
    )
    if fallback_group_error:
        return None, fallback_group_error
    if fallback_group_id is not None:
        return ("group", fallback_group_id), None

    fallback_user_id, fallback_user_error = _parse_positive_int(
        context.get("user_id"), "user_id"
    )
    if fallback_user_error:
        return None, fallback_user_error
    if fallback_user_id is not None:
        return ("private", fallback_user_id), None

    return None, "无法确定目标会话，请提供 target_type 与 target_id"


def _is_current_group_target(context: Dict[str, Any], target_id: int) -> bool:
    context_group_id, _ = _parse_positive_int(context.get("group_id"), "group_id")
    return context_group_id == target_id


def _is_current_private_target(context: Dict[str, Any], target_id: int) -> bool:
    context_user_id, _ = _parse_positive_int(context.get("user_id"), "user_id")
    return context_user_id == target_id


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    """发送消息，支持群聊/私聊与 CQ 码格式"""
    request_id = str(context.get("request_id", "-"))
    message = str(args.get("message", ""))
    if not message:
        logger.warning("[发送消息] 收到空消息请求")
        return "消息内容不能为空"

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
            return f"发送失败：目标群 {target_id} 不在允许列表内（access.allowed_group_ids），已被访问控制拦截"
        if target_type == "private" and not runtime_config.is_private_allowed(
            target_id
        ):
            return f"发送失败：目标用户 {target_id} 不在允许列表内（access.allowed_private_ids），已被访问控制拦截"

    if sender:
        try:
            if target_type == "group":
                logger.info("[发送消息] 准备发送到群 %s: %s", target_id, message[:100])
                await sender.send_group_message(target_id, message)
            else:
                logger.info("[发送消息] 准备发送私聊 %s: %s", target_id, message[:100])
                await sender.send_private_message(target_id, message)
            context["message_sent_this_turn"] = True
            return "消息已发送"
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
                await send_message_callback(message)
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
            await send_private_message_callback(target_id, message)
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
            await send_message_callback(message)
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
