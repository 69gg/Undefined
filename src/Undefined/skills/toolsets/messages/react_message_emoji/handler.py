from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Literal

from Undefined.context import RequestContext
from Undefined.utils.qq_emoji import resolve_emoji_id_by_alias, search_emoji_aliases

logger = logging.getLogger(__name__)

TargetType = Literal["group", "private"]
ActionType = Literal["set", "unset"]

_SEEN_OPS_KEY = "_emoji_reaction_seen_ops"
_MESSAGE_LOCKS: dict[int, asyncio.Lock] = {}
_MESSAGE_LOCKS_GUARD = asyncio.Lock()


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


def _parse_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return default


def _snapshot_context(context: Dict[str, Any]) -> dict[str, Any]:
    ctx = RequestContext.current()

    request_type = context.get("request_type")
    group_id = context.get("group_id")
    user_id = context.get("user_id")
    sender_id = context.get("sender_id")
    request_id = context.get("request_id")
    trigger_message_id = context.get("trigger_message_id")

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
        if trigger_message_id is None:
            trigger_message_id = ctx.get_resource("trigger_message_id")

    return {
        "request_type": request_type,
        "group_id": group_id,
        "user_id": user_id,
        "sender_id": sender_id,
        "request_id": request_id,
        "trigger_message_id": trigger_message_id,
    }


def _resolve_action(args: Dict[str, Any]) -> tuple[ActionType | None, str | None]:
    action_raw = args.get("action")
    if action_raw is None:
        return "set", None
    if not isinstance(action_raw, str):
        return None, "action 必须是字符串（set 或 unset）"
    action = action_raw.strip().lower()
    if action not in ("set", "unset"):
        return None, "action 只能是 set 或 unset"
    return ("set" if action == "set" else "unset"), None


def _resolve_message_id(
    args: Dict[str, Any], snapshot: dict[str, Any]
) -> tuple[int | None, str | None]:
    direct_id, direct_error = _parse_positive_int(args.get("message_id"), "message_id")
    if direct_error:
        return None, direct_error
    if direct_id is not None:
        return direct_id, None

    trigger_id, trigger_error = _parse_positive_int(
        snapshot.get("trigger_message_id"), "trigger_message_id"
    )
    if trigger_error:
        return None, trigger_error
    if trigger_id is not None:
        return trigger_id, None

    return None, "无法确定目标消息，请提供 message_id 参数"


def _resolve_emoji_id(args: Dict[str, Any]) -> tuple[int | None, str | None]:
    emoji_id, emoji_id_error = _parse_positive_int(args.get("emoji_id"), "emoji_id")
    if emoji_id_error:
        return None, emoji_id_error
    if emoji_id is not None:
        return emoji_id, None

    emoji_raw = args.get("emoji")
    if emoji_raw is None:
        return None, "请提供 emoji_id 或 emoji"
    if not isinstance(emoji_raw, str):
        return None, "emoji 必须是字符串"
    emoji = emoji_raw.strip()
    if not emoji:
        return None, "emoji 不能为空字符串"

    resolved = resolve_emoji_id_by_alias(emoji)
    if resolved is not None:
        return resolved, None

    suggestions = search_emoji_aliases(emoji, limit=5)
    if suggestions:
        tip = "，".join(f"{alias}->{eid}" for alias, eid in suggestions)
        return (
            None,
            f"emoji '{emoji}' 未匹配到 ID。你可以先用 messages.lookup_emoji_id / messages.list_emojis 查询。候选：{tip}",
        )
    return (
        None,
        f"emoji '{emoji}' 未匹配到 ID。请改用 emoji_id，或先调用 messages.lookup_emoji_id / messages.list_emojis。",
    )


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


def _get_seen_ops(context: Dict[str, Any]) -> set[str]:
    seen = context.get(_SEEN_OPS_KEY)
    if isinstance(seen, set):
        return seen

    ctx = RequestContext.current()
    if ctx is not None:
        seen_in_ctx = ctx.get_resource(_SEEN_OPS_KEY)
        if isinstance(seen_in_ctx, set):
            context[_SEEN_OPS_KEY] = seen_in_ctx
            return seen_in_ctx

    created: set[str] = set()
    context[_SEEN_OPS_KEY] = created
    if ctx is not None:
        ctx.set_resource(_SEEN_OPS_KEY, created)
    return created


async def _get_message_lock(message_id: int) -> asyncio.Lock:
    async with _MESSAGE_LOCKS_GUARD:
        lock = _MESSAGE_LOCKS.get(message_id)
        if lock is None:
            lock = asyncio.Lock()
            _MESSAGE_LOCKS[message_id] = lock
        return lock


def _resolve_target_constraint(
    args: Dict[str, Any],
) -> tuple[tuple[TargetType, int] | None, str | None]:
    target_type_raw = args.get("target_type")
    target_id_raw = args.get("target_id")
    has_target_type = target_type_raw is not None
    has_target_id = target_id_raw is not None

    if not has_target_type and not has_target_id:
        return None, None
    if has_target_type != has_target_id:
        return None, "target_type 与 target_id 必须同时提供"

    if not isinstance(target_type_raw, str):
        return None, "target_type 必须是字符串（group 或 private）"
    normalized_type = target_type_raw.strip().lower()
    if normalized_type not in ("group", "private"):
        return None, "target_type 只能是 group 或 private"

    parsed_target_id, target_id_error = _parse_positive_int(target_id_raw, "target_id")
    if target_id_error or parsed_target_id is None:
        return None, target_id_error or "target_id 非法"

    target_type: TargetType = "group" if normalized_type == "group" else "private"
    return (target_type, parsed_target_id), None


def _extract_message_location(
    message_detail: dict[str, Any],
) -> tuple[TargetType, int] | None:
    message_type_raw = str(message_detail.get("message_type", "")).strip().lower()

    if message_type_raw == "group":
        group_id, _ = _parse_positive_int(message_detail.get("group_id"), "group_id")
        if group_id is not None:
            return ("group", group_id)
    elif message_type_raw == "private":
        user_id, _ = _parse_positive_int(message_detail.get("user_id"), "user_id")
        if user_id is not None:
            return ("private", user_id)

    # 兜底推断
    group_id, _ = _parse_positive_int(message_detail.get("group_id"), "group_id")
    if group_id is not None:
        return ("group", group_id)

    user_id, _ = _parse_positive_int(message_detail.get("user_id"), "user_id")
    if user_id is not None:
        return ("private", user_id)
    return None


def _resolve_current_session_target(
    snapshot: dict[str, Any],
) -> tuple[TargetType, int] | None:
    request_type = snapshot.get("request_type")
    if request_type == "group":
        group_id, _ = _parse_positive_int(snapshot.get("group_id"), "group_id")
        if group_id is not None:
            return ("group", group_id)
    if request_type == "private":
        user_id, _ = _parse_positive_int(snapshot.get("user_id"), "user_id")
        if user_id is not None:
            return ("private", user_id)
    return None


def _validate_target_and_allowlist(
    *,
    snapshot: dict[str, Any],
    constraint: tuple[TargetType, int] | None,
    message_location: tuple[TargetType, int] | None,
    strict_current_session: bool,
    runtime_config: Any | None,
) -> str | None:
    if (
        constraint is not None
        and message_location is not None
        and constraint != message_location
    ):
        return (
            f"目标会话校验失败：目标约束为 {constraint[0]}:{constraint[1]}，"
            f"但消息属于 {message_location[0]}:{message_location[1]}"
        )

    if strict_current_session:
        current_target = _resolve_current_session_target(snapshot)
        if current_target is None:
            return "当前请求没有可用会话信息，无法校验消息归属"
        if message_location is None:
            return "无法识别目标消息所属会话，已拒绝操作（strict_current_session=true）"
        if current_target != message_location:
            return (
                f"目标消息不属于当前会话：当前会话 {current_target[0]}:{current_target[1]}，"
                f"消息会话 {message_location[0]}:{message_location[1]}"
            )

    effective_target = message_location or constraint
    if effective_target is None or runtime_config is None:
        return None

    target_type, target_id = effective_target
    if target_type == "group" and not runtime_config.is_group_allowed(target_id):
        return (
            f"目标群 {target_id} 不在允许列表内（access.allowed_group_ids），"
            "已被访问控制拦截"
        )
    if target_type == "private" and not runtime_config.is_private_allowed(target_id):
        return (
            f"目标用户 {target_id} 不在允许列表内（access.allowed_private_ids），"
            "已被访问控制拦截"
        )
    return None


def _extract_reaction_state(fetch_data: Any, emoji_id: int) -> bool | None:
    """从 fetch_emoji_like 的返回中提取当前 emoji 是否已设置。

    返回:
        True: 已设置
        False: 未设置
        None: 无法判断
    """

    def _is_match_id(raw: Any) -> bool:
        try:
            return int(raw) == emoji_id
        except (TypeError, ValueError):
            return False

    def _entry_state(entry: dict[str, Any]) -> bool | None:
        for key in ("emoji_id", "id", "face_id"):
            if key in entry and not _is_match_id(entry.get(key)):
                return None

        for key in ("is_liked", "liked", "is_set", "set"):
            if key in entry:
                val = entry.get(key)
                if isinstance(val, bool):
                    return val
                if isinstance(val, int):
                    return val > 0
                if isinstance(val, str):
                    lowered = val.strip().lower()
                    if lowered in {"1", "true", "yes"}:
                        return True
                    if lowered in {"0", "false", "no"}:
                        return False
        for key in ("count", "total"):
            if key in entry:
                try:
                    return int(entry.get(key, 0)) > 0
                except (TypeError, ValueError):
                    pass
        return None

    if isinstance(fetch_data, list):
        matched_any = False
        for item in fetch_data:
            if not isinstance(item, dict):
                continue
            item_id = item.get("emoji_id", item.get("id", item.get("face_id")))
            if not _is_match_id(item_id):
                continue
            matched_any = True
            state = _entry_state(item)
            if state is not None:
                return state
            return True
        return False if matched_any else None

    if isinstance(fetch_data, dict):
        # 形式 A：{"76": 3, ...}
        if str(emoji_id) in fetch_data:
            val = fetch_data.get(str(emoji_id))
            if val is None:
                return False
            if isinstance(val, bool):
                return val
            try:
                return int(val) > 0
            except (TypeError, ValueError):
                return True

        # 形式 B：嵌套列表字段
        for key in ("emoji_likes", "emojiLikes", "likes", "list", "data"):
            state = _extract_reaction_state(fetch_data.get(key), emoji_id)
            if state is not None:
                return state

        # 形式 C：单条对象
        item_id = fetch_data.get(
            "emoji_id", fetch_data.get("id", fetch_data.get("face_id"))
        )
        if item_id is not None and _is_match_id(item_id):
            object_state = _entry_state(fetch_data)
            return object_state if object_state is not None else True
    return None


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    snapshot = _snapshot_context(context)
    request_id = str(snapshot.get("request_id") or "-")

    action, action_error = _resolve_action(args)
    if action_error or action is None:
        return f"操作失败：{action_error or 'action 参数错误'}"

    message_id, message_error = _resolve_message_id(args, snapshot)
    if message_error or message_id is None:
        return f"操作失败：{message_error or 'message_id 参数错误'}"

    emoji_id, emoji_error = _resolve_emoji_id(args)
    if emoji_error or emoji_id is None:
        return f"操作失败：{emoji_error or 'emoji 参数错误'}"

    strict_current_session = _parse_bool(args.get("strict_current_session"), True)
    target_constraint, target_error = _resolve_target_constraint(args)
    if target_error:
        return f"操作失败：{target_error}"

    onebot_client = _resolve_onebot_client(context)
    if onebot_client is None:
        logger.error("[消息表情] OneBot 客户端不可用: request_id=%s", request_id)
        return "操作失败：OneBot 客户端未连接"

    get_msg = getattr(onebot_client, "get_msg", None)
    set_emoji_like = getattr(onebot_client, "set_msg_emoji_like", None)
    fetch_emoji_like = getattr(onebot_client, "fetch_emoji_like", None)
    if not callable(set_emoji_like):
        return "操作失败：当前环境不支持消息表情反应接口"

    lock = await _get_message_lock(message_id)
    async with lock:
        seen_ops = _get_seen_ops(context)
        op_key = f"{message_id}:{emoji_id}:{action}"
        if op_key in seen_ops:
            return (
                f"已跳过重复操作：消息 {message_id} 的 emoji_id={emoji_id} "
                f"已处理 action={action}"
            )

        message_detail: dict[str, Any] | None = None
        if callable(get_msg):
            try:
                detail = await get_msg(message_id)
                if isinstance(detail, dict):
                    message_detail = detail
            except Exception as exc:
                logger.warning(
                    "[消息表情] 获取消息详情失败: request_id=%s message_id=%s err=%s",
                    request_id,
                    message_id,
                    exc,
                )

        message_location = (
            _extract_message_location(message_detail) if message_detail else None
        )
        runtime_config = context.get("runtime_config")
        validation_error = _validate_target_and_allowlist(
            snapshot=snapshot,
            constraint=target_constraint,
            message_location=message_location,
            strict_current_session=strict_current_session,
            runtime_config=runtime_config,
        )
        if validation_error:
            return f"操作失败：{validation_error}"

        desired_state = action == "set"
        current_state: bool | None = None
        if callable(fetch_emoji_like):
            try:
                fetch_data = await fetch_emoji_like(message_id)
                current_state = _extract_reaction_state(fetch_data, emoji_id)
            except Exception as exc:
                logger.info(
                    "[消息表情] fetch_emoji_like 不可用或失败，跳过幂等预检查: request_id=%s message_id=%s err=%s",
                    request_id,
                    message_id,
                    exc,
                )

        if current_state is not None and current_state == desired_state:
            seen_ops.add(op_key)
            if desired_state:
                return f"消息 {message_id} 已有 emoji_id={emoji_id}，无需重复添加"
            return f"消息 {message_id} 当前未设置 emoji_id={emoji_id}，无需取消"

        try:
            await set_emoji_like(message_id, emoji_id, set_like=desired_state)
            _mark_action_sent(context)
            seen_ops.add(op_key)
            if desired_state:
                return f"已为消息 {message_id} 添加表情（emoji_id={emoji_id}）"
            return f"已为消息 {message_id} 取消表情（emoji_id={emoji_id}）"
        except Exception as exc:
            logger.exception(
                "[消息表情] 操作失败: request_id=%s message_id=%s emoji_id=%s action=%s err=%s",
                request_id,
                message_id,
                emoji_id,
                action,
                exc,
            )
            return (
                "操作失败：消息表情服务暂时不可用。"
                "请确认 OneBot 实现支持 set_msg_emoji_like / fetch_emoji_like 扩展接口。"
            )
