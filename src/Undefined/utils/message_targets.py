from __future__ import annotations

from typing import Any, Literal


TargetType = Literal["group", "private"]


def parse_positive_int(value: Any, field_name: str) -> tuple[int | None, str | None]:
    if value is None:
        return None, None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None, f"{field_name} 必须是整数"
    if parsed <= 0:
        return None, f"{field_name} 必须是正整数"
    return parsed, None


def resolve_message_target(
    args: dict[str, Any], context: dict[str, Any]
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
            target_id, id_error = parse_positive_int(target_id_raw, "target_id")
            if id_error or target_id is None:
                return None, id_error or "target_id 非法"
            return (normalized_target_type, target_id), None

        request_type = context.get("request_type")
        if request_type != normalized_target_type:
            return None, "target_type 与当前会话类型不一致，无法推断 target_id"

        if normalized_target_type == "group":
            group_id, group_error = parse_positive_int(
                context.get("group_id"), "group_id"
            )
            if group_error or group_id is None:
                return None, group_error or "无法根据 target_type 推断 target_id"
            return ("group", group_id), None

        user_id, user_error = parse_positive_int(context.get("user_id"), "user_id")
        if user_error or user_id is None:
            return None, user_error or "无法根据 target_type 推断 target_id"
        return ("private", user_id), None

    legacy_group_id = args.get("group_id")
    if legacy_group_id is not None:
        group_id, group_error = parse_positive_int(legacy_group_id, "group_id")
        if group_error or group_id is None:
            return None, group_error or "group_id 非法"
        return ("group", group_id), None

    legacy_user_id = args.get("user_id")
    if legacy_user_id is not None:
        user_id, user_error = parse_positive_int(legacy_user_id, "user_id")
        if user_error or user_id is None:
            return None, user_error or "user_id 非法"
        return ("private", user_id), None

    request_type = context.get("request_type")
    if request_type == "group":
        group_id, group_error = parse_positive_int(context.get("group_id"), "group_id")
        if group_error:
            return None, group_error
        if group_id is not None:
            return ("group", group_id), None
    elif request_type == "private":
        user_id, user_error = parse_positive_int(context.get("user_id"), "user_id")
        if user_error:
            return None, user_error
        if user_id is not None:
            return ("private", user_id), None

    fallback_group_id, fallback_group_error = parse_positive_int(
        context.get("group_id"), "group_id"
    )
    if fallback_group_error:
        return None, fallback_group_error
    if fallback_group_id is not None:
        return ("group", fallback_group_id), None

    fallback_user_id, fallback_user_error = parse_positive_int(
        context.get("user_id"), "user_id"
    )
    if fallback_user_error:
        return None, fallback_user_error
    if fallback_user_id is not None:
        return ("private", fallback_user_id), None

    return None, "无法确定目标会话，请提供 target_type 与 target_id"
