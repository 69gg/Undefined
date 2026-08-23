"""Resolve automation delivery addresses, including leftover target_id fields."""

from __future__ import annotations

from Undefined.utils.message_targets import DeliveryAddress, parse_delivery_address


def resolve_live_event_address(
    *,
    address: str = "",
    channel: str = "",
    group_id: int | None = None,
    user_id: int | None = None,
) -> DeliveryAddress | None:
    """Resolve delivery from the triggering session, never a stored task target."""
    if str(address or "").strip():
        return resolve_task_address(address, None, "group")
    if channel == "group" and group_id is not None:
        return resolve_task_address(None, group_id, "group")
    if user_id is not None:
        return resolve_task_address(None, user_id, "private")
    return None


def resolve_task_address(
    address: object,
    target_id: int | None,
    target_type: str,
) -> DeliveryAddress | None:
    address_text = str(address or "").strip()
    explicit_address: DeliveryAddress | None = None
    if address_text:
        explicit_address, error = parse_delivery_address(address_text)
        if error or explicit_address is None:
            raise ValueError(error or "投递地址无效")

    legacy_address: DeliveryAddress | None = None
    if target_id is not None:
        legacy_type = str(target_type or "group").strip().lower()
        if legacy_type not in {"group", "private"}:
            raise ValueError("target_type 只能是 group 或 private")
        channel = "group" if legacy_type == "group" else "qq"
        legacy_address, error = parse_delivery_address(f"{channel}:{target_id}")
        if error or legacy_address is None:
            raise ValueError(error or "投递目标无效")

    if explicit_address is not None:
        if legacy_address is not None and legacy_address != explicit_address:
            raise ValueError("address 与旧目标参数指向不同会话")
        return explicit_address
    return legacy_address


def legacy_target_fields(address: DeliveryAddress) -> tuple[int | None, str]:
    if address.channel == "wechat":
        return None, "private"
    return address.target_id, address.target_type
