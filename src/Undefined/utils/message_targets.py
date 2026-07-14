"""消息投递地址解析。

逻辑身份始终使用 QQ 号；``channel`` 仅描述物理投递通道。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


TargetType = Literal["group", "private"]
DeliveryChannel = Literal["qq", "group", "wechat"]


@dataclass(frozen=True, slots=True)
class DeliveryAddress:
    """一个规范化的消息投递地址。"""

    channel: DeliveryChannel
    target_id: int

    @property
    def target_type(self) -> TargetType:
        return "group" if self.channel == "group" else "private"

    @property
    def canonical(self) -> str:
        return f"{self.channel}:{self.target_id}"

    @property
    def logical_user_id(self) -> int | None:
        return self.target_id if self.target_type == "private" else None


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


def parse_delivery_address(
    value: Any,
    *,
    field_name: str = "address",
) -> tuple[DeliveryAddress | None, str | None]:
    """解析 ``qq:<id>``、``group:<id>`` 或 ``wechat:<id>``。"""
    if value is None:
        return None, None
    if not isinstance(value, str):
        return None, f"{field_name} 必须是字符串"
    text = value.strip().lower()
    channel_text, separator, target_text = text.partition(":")
    if not separator or not channel_text or not target_text:
        return None, (
            f"{field_name} 格式错误，应为 qq:<QQ号>、group:<群号> 或 wechat:<QQ号>"
        )
    if channel_text not in {"qq", "group", "wechat"}:
        return None, f"{field_name} 通道只能是 qq、group 或 wechat"
    target_id, error = parse_positive_int(target_text, field_name)
    if error or target_id is None:
        return None, error or f"{field_name} 非法"
    channel: DeliveryChannel
    if channel_text == "group":
        channel = "group"
    elif channel_text == "wechat":
        channel = "wechat"
    else:
        channel = "qq"
    return DeliveryAddress(channel=channel, target_id=target_id), None


def _legacy_explicit_address(
    args: dict[str, Any],
    context: dict[str, Any],
) -> tuple[DeliveryAddress | None, str | None, bool]:
    target_type_raw = args.get("target_type")
    target_id_raw = args.get("target_id")
    has_target_type = target_type_raw is not None
    has_target_id = target_id_raw is not None

    if has_target_type or has_target_id:
        if not has_target_type and has_target_id:
            return None, "target_type 与 target_id 必须同时提供", True
        if not isinstance(target_type_raw, str):
            return None, "target_type 必须是字符串（group 或 private）", True
        target_type = target_type_raw.strip().lower()
        if target_type not in ("group", "private"):
            return None, "target_type 只能是 group 或 private", True
        normalized_type: TargetType = "group" if target_type == "group" else "private"
        if has_target_id:
            target_id, error = parse_positive_int(target_id_raw, "target_id")
            if error or target_id is None:
                return None, error or "target_id 非法", True
            channel: DeliveryChannel = "group" if normalized_type == "group" else "qq"
            return DeliveryAddress(channel, target_id), None, True

        if context.get("request_type") != normalized_type:
            return None, "target_type 与当前会话类型不一致，无法推断 target_id", True
        id_field = "group_id" if normalized_type == "group" else "user_id"
        target_id, error = parse_positive_int(context.get(id_field), id_field)
        if error or target_id is None:
            return None, error or "无法根据 target_type 推断 target_id", True
        channel = "group" if normalized_type == "group" else "qq"
        return DeliveryAddress(channel, target_id), None, True

    legacy_group_id = args.get("group_id")
    if legacy_group_id is not None:
        group_id, error = parse_positive_int(legacy_group_id, "group_id")
        if error or group_id is None:
            return None, error or "group_id 非法", True
        return DeliveryAddress("group", group_id), None, True

    legacy_user_id = args.get("user_id")
    if legacy_user_id is not None:
        user_id, error = parse_positive_int(legacy_user_id, "user_id")
        if error or user_id is None:
            return None, error or "user_id 非法", True
        return DeliveryAddress("qq", user_id), None, True

    return None, None, False


def resolve_delivery_address(
    args: dict[str, Any],
    context: dict[str, Any],
) -> tuple[DeliveryAddress | None, str | None]:
    """按显式地址、旧参数、当前地址、当前会话的顺序解析目标。"""
    explicit_address, address_error = parse_delivery_address(args.get("address"))
    if address_error:
        return None, address_error

    legacy_address, legacy_error, has_legacy = _legacy_explicit_address(args, context)
    if legacy_error:
        return None, legacy_error
    if explicit_address is not None:
        if has_legacy and legacy_address != explicit_address:
            return None, "address 与旧目标参数指向不同会话"
        return explicit_address, None
    if has_legacy:
        return legacy_address, None

    context_address, context_error = parse_delivery_address(context.get("address"))
    if context_error:
        return None, f"当前会话 {context_error}"
    if context_address is not None:
        return context_address, None

    request_type = context.get("request_type")
    if request_type == "group":
        group_id, error = parse_positive_int(context.get("group_id"), "group_id")
        if error:
            return None, error
        if group_id is not None:
            return DeliveryAddress("group", group_id), None
    elif request_type == "private":
        user_id, error = parse_positive_int(context.get("user_id"), "user_id")
        if error:
            return None, error
        if user_id is not None:
            return DeliveryAddress("qq", user_id), None

    fallback_group_id, group_error = parse_positive_int(
        context.get("group_id"), "group_id"
    )
    if group_error:
        return None, group_error
    if fallback_group_id is not None:
        return DeliveryAddress("group", fallback_group_id), None

    fallback_user_id, user_error = parse_positive_int(context.get("user_id"), "user_id")
    if user_error:
        return None, user_error
    if fallback_user_id is not None:
        return DeliveryAddress("qq", fallback_user_id), None

    return None, "无法确定目标会话，请提供 address 或 target_type 与 target_id"


def resolve_message_target(
    args: dict[str, Any], context: dict[str, Any]
) -> tuple[tuple[TargetType, int] | None, str | None]:
    """旧版元组接口；新代码应使用 :func:`resolve_delivery_address`。"""
    address, error = resolve_delivery_address(args, context)
    if error or address is None:
        return None, error
    return (address.target_type, address.target_id), None
