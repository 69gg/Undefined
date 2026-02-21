from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any, Dict, Literal, cast

from Undefined.context import RequestContext

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


def _snapshot_context(context: Dict[str, Any]) -> dict[str, Any]:
    """冻结当前上下文关键字段，避免执行期间上下文变化导致竞态。"""
    ctx = RequestContext.current()

    request_type = context.get("request_type")
    group_id = context.get("group_id")
    user_id = context.get("user_id")
    sender_id = context.get("sender_id")
    request_id = context.get("request_id")

    if ctx is not None:
        if request_type is None:
            request_type = ctx.request_type
        if group_id is None:
            group_id = ctx.group_id
        if user_id is None:
            user_id = ctx.user_id
        if sender_id is None:
            sender_id = ctx.sender_id
        if request_id is None:
            request_id = ctx.request_id

    return {
        "request_type": request_type,
        "group_id": group_id,
        "user_id": user_id,
        "sender_id": sender_id,
        "request_id": request_id,
    }


def _resolve_send_target(
    args: Dict[str, Any], snapshot: dict[str, Any]
) -> tuple[tuple[TargetType, int] | None, str | None]:
    target_type_raw = args.get("target_type")
    target_id_raw = args.get("target_id")
    has_target_type = target_type_raw is not None
    has_target_id = target_id_raw is not None

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
            target_id, target_error = _parse_positive_int(target_id_raw, "target_id")
            if target_error or target_id is None:
                return None, target_error or "target_id 非法"
            return (normalized_target_type, target_id), None

        request_type = snapshot.get("request_type")
        if request_type != normalized_target_type:
            return None, "target_type 与当前会话类型不一致，无法推断 target_id"

        if normalized_target_type == "group":
            group_id, group_error = _parse_positive_int(
                snapshot.get("group_id"), "group_id"
            )
            if group_error or group_id is None:
                return None, group_error or "无法根据 target_type 推断 target_id"
            return ("group", group_id), None

        user_id, user_error = _parse_positive_int(snapshot.get("user_id"), "user_id")
        if user_error or user_id is None:
            return None, user_error or "无法根据 target_type 推断 target_id"
        return ("private", user_id), None

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

    request_type = snapshot.get("request_type")
    if request_type == "group":
        group_id, group_error = _parse_positive_int(
            snapshot.get("group_id"), "group_id"
        )
        if group_error:
            return None, group_error
        if group_id is not None:
            return ("group", group_id), None
    elif request_type == "private":
        user_id, user_error = _parse_positive_int(snapshot.get("user_id"), "user_id")
        if user_error:
            return None, user_error
        if user_id is not None:
            return ("private", user_id), None

    fallback_group_id, fallback_group_error = _parse_positive_int(
        snapshot.get("group_id"), "group_id"
    )
    if fallback_group_error:
        return None, fallback_group_error
    if fallback_group_id is not None:
        return ("group", fallback_group_id), None

    fallback_user_id, fallback_user_error = _parse_positive_int(
        snapshot.get("user_id"), "user_id"
    )
    if fallback_user_error:
        return None, fallback_user_error
    if fallback_user_id is not None:
        return ("private", fallback_user_id), None

    return None, "无法确定发送位置，请提供 target_type 与 target_id"


def _resolve_target_user(
    args: Dict[str, Any],
    snapshot: dict[str, Any],
    send_target: tuple[TargetType, int],
) -> tuple[int | None, str | None]:
    target_user_raw = args.get("target_user_id")
    target_type, target_id = send_target
    if target_user_raw is not None:
        target_user_id, target_user_error = _parse_positive_int(
            target_user_raw, "target_user_id"
        )
        if target_user_error or target_user_id is None:
            return None, target_user_error or "target_user_id 非法"
        if target_type == "private" and target_user_id != target_id:
            return (
                None,
                f"target_user_id={target_user_id} 与私聊目标 target_id={target_id} 不一致",
            )
        return target_user_id, None

    if target_type == "private":
        return target_id, None

    sender_id, sender_error = _parse_positive_int(
        snapshot.get("sender_id"), "sender_id"
    )
    if sender_error:
        return None, sender_error
    if sender_id is not None:
        return sender_id, None

    fallback_user_id, fallback_user_error = _parse_positive_int(
        snapshot.get("user_id"), "user_id"
    )
    if fallback_user_error:
        return None, fallback_user_error
    if fallback_user_id is not None:
        return fallback_user_id, None

    return None, "无法确定被拍目标，请提供 target_user_id"


def _resolve_onebot_client(context: Dict[str, Any]) -> Any | None:
    onebot_client = context.get("onebot_client")
    if onebot_client is not None:
        return onebot_client

    sender = context.get("sender")
    if sender is not None:
        sender_onebot = getattr(sender, "onebot", None)
        if sender_onebot is not None:
            return sender_onebot

    ctx = RequestContext.current()
    if ctx is None:
        return None

    return ctx.get_resource("onebot_client")


def _mark_action_sent(context: Dict[str, Any]) -> None:
    context["message_sent_this_turn"] = True
    ctx = RequestContext.current()
    if ctx is not None:
        ctx.set_resource("message_sent_this_turn", True)


def _resolve_bot_qq(context: Dict[str, Any]) -> int:
    runtime_config = context.get("runtime_config")
    bot_qq_raw = getattr(runtime_config, "bot_qq", 0)
    try:
        return int(bot_qq_raw)
    except (TypeError, ValueError):
        return 0


def _group_access_error(runtime_config: Any, group_id: int) -> str:
    reason_getter = getattr(runtime_config, "group_access_denied_reason", None)
    reason = reason_getter(group_id) if callable(reason_getter) else None
    if reason == "blacklist":
        return (
            f"发送失败：目标群 {group_id} 在黑名单内（access.blocked_group_ids），"
            "已被访问控制拦截"
        )
    return (
        f"发送失败：目标群 {group_id} 不在允许列表内（access.allowed_group_ids），"
        "已被访问控制拦截"
    )


def _private_access_error(user_id: int) -> str:
    return (
        f"发送失败：目标用户 {user_id} 不在允许列表内（access.allowed_private_ids），"
        "已被访问控制拦截"
    )


async def _record_poke_history_if_needed(
    context: Dict[str, Any],
    target_type: TargetType,
    target_id: int,
    target_user_id: int,
) -> None:
    history_manager = context.get("history_manager")
    if history_manager is None:
        return

    message = f"(拍了拍 QQ{target_user_id})"
    bot_qq = _resolve_bot_qq(context)

    try:
        if target_type == "group":
            await history_manager.add_group_message(
                group_id=target_id,
                sender_id=bot_qq,
                text_content=message,
                sender_nickname="Bot",
                group_name="",
            )
        else:
            await history_manager.add_private_message(
                user_id=target_user_id,
                text_content=message,
                display_name="Bot",
                user_name="Bot",
            )
    except Exception:
        logger.exception(
            "[拍一拍] 记录历史失败: target_type=%s target_id=%s user=%s",
            target_type,
            target_id,
            target_user_id,
        )


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    request_snapshot = _snapshot_context(context)
    request_id = str(request_snapshot.get("request_id") or "-")

    send_target, target_error = _resolve_send_target(args, request_snapshot)
    if target_error or send_target is None:
        logger.warning(
            "[拍一拍] 发送位置解析失败: request_id=%s err=%s", request_id, target_error
        )
        return f"发送失败：{target_error or '发送位置参数错误'}"

    target_user_id, target_user_error = _resolve_target_user(
        args, request_snapshot, send_target
    )
    if target_user_error or target_user_id is None:
        logger.warning(
            "[拍一拍] 目标用户解析失败: request_id=%s err=%s",
            request_id,
            target_user_error,
        )
        return f"发送失败：{target_user_error or '目标用户参数错误'}"

    target_type, target_id = send_target

    runtime_config = context.get("runtime_config")
    if runtime_config is not None:
        if target_type == "group" and not runtime_config.is_group_allowed(target_id):
            return _group_access_error(runtime_config, target_id)
        if target_type == "private" and not runtime_config.is_private_allowed(
            target_user_id
        ):
            return _private_access_error(target_user_id)

    sender = context.get("sender")
    if sender is not None:
        try:
            if target_type == "group":
                send_group_poke = getattr(sender, "send_group_poke", None)
                if callable(send_group_poke):
                    await cast(Callable[[int, int], Awaitable[Any]], send_group_poke)(
                        target_id, target_user_id
                    )
                    _mark_action_sent(context)
                    await _record_poke_history_if_needed(
                        context, target_type, target_id, target_user_id
                    )
                    return f"已在群 {target_id} 拍了拍 QQ{target_user_id}"
            else:
                send_private_poke = getattr(sender, "send_private_poke", None)
                if callable(send_private_poke):
                    await cast(Callable[[int], Awaitable[Any]], send_private_poke)(
                        target_user_id
                    )
                    _mark_action_sent(context)
                    await _record_poke_history_if_needed(
                        context, target_type, target_id, target_user_id
                    )
                    return f"已拍了拍 QQ{target_user_id}"
        except PermissionError:
            logger.warning(
                "[拍一拍] sender 发送被访问控制拦截: request_id=%s target_type=%s target_id=%s user=%s",
                request_id,
                target_type,
                target_id,
                target_user_id,
            )
            if target_type == "group":
                return _group_access_error(runtime_config, target_id)
            return _private_access_error(target_user_id)
        except Exception as e:
            logger.exception(
                "[拍一拍] sender 发送失败: request_id=%s target_type=%s target_id=%s user=%s err=%s",
                request_id,
                target_type,
                target_id,
                target_user_id,
                e,
            )
            return "发送失败：拍一拍服务暂时不可用，请稍后重试"

    onebot_client = _resolve_onebot_client(context)
    if onebot_client is None:
        logger.error("[拍一拍] OneBot 客户端不可用: request_id=%s", request_id)
        return "发送失败：OneBot 客户端未连接"

    try:
        if target_type == "group":
            send_group_poke = getattr(onebot_client, "send_group_poke", None)
            if not callable(send_group_poke):
                return "发送失败：当前环境不支持群聊拍一拍"
            await cast(Callable[[int, int], Awaitable[Any]], send_group_poke)(
                target_id,
                target_user_id,
            )
            _mark_action_sent(context)
            await _record_poke_history_if_needed(
                context, target_type, target_id, target_user_id
            )
            return f"已在群 {target_id} 拍了拍 QQ{target_user_id}"

        send_private_poke = getattr(onebot_client, "send_private_poke", None)
        if not callable(send_private_poke):
            return "发送失败：当前环境不支持私聊拍一拍"
        await cast(Callable[[int], Awaitable[Any]], send_private_poke)(target_user_id)
        _mark_action_sent(context)
        await _record_poke_history_if_needed(
            context, target_type, target_id, target_user_id
        )
        return f"已拍了拍 QQ{target_user_id}"
    except Exception as e:
        logger.exception(
            "[拍一拍] OneBot 发送失败: request_id=%s target_type=%s target_id=%s user=%s err=%s",
            request_id,
            target_type,
            target_id,
            target_user_id,
            e,
        )
        return "发送失败：拍一拍服务暂时不可用，请稍后重试"
