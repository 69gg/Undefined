from __future__ import annotations

import asyncio
from typing import Any

from Undefined.services.commands.context import CommandContext


_UNKNOWN_MEMBER_NAME = "未知成员"


def _extract_display_name(user_info: dict[str, Any] | None) -> str | None:
    if not isinstance(user_info, dict):
        return None
    for field in ("card", "nickname", "remark"):
        value = str(user_info.get(field) or "").strip()
        if value:
            return value
    return None


async def _load_group_member_names(context: CommandContext) -> dict[int, str]:
    if context.group_id <= 0:
        return {}

    get_group_member_list = getattr(context.onebot, "get_group_member_list", None)
    if not callable(get_group_member_list):
        return {}

    try:
        members = await get_group_member_list(context.group_id)
    except Exception:
        return {}

    names: dict[int, str] = {}
    if not isinstance(members, list):
        return names

    for member in members:
        if not isinstance(member, dict):
            continue
        user_id_raw = member.get("user_id")
        if user_id_raw is None:
            continue
        try:
            user_id = int(user_id_raw)
        except (TypeError, ValueError):
            continue
        display_name = _extract_display_name(member)
        if display_name:
            names[user_id] = display_name
    return names


async def _load_qq_names(
    context: CommandContext,
    user_ids: list[int],
) -> dict[int, str]:
    get_stranger_info = getattr(context.onebot, "get_stranger_info", None)
    if not callable(get_stranger_info) or not user_ids:
        return {}

    results = await asyncio.gather(
        *(get_stranger_info(user_id) for user_id in user_ids),
        return_exceptions=True,
    )

    names: dict[int, str] = {}
    for user_id, result in zip(user_ids, results, strict=False):
        if isinstance(result, Exception):
            continue
        if result is not None and not isinstance(result, dict):
            continue
        display_name = _extract_display_name(result)
        if display_name:
            names[user_id] = display_name
    return names


async def _resolve_admin_names(
    context: CommandContext,
    user_ids: list[int],
) -> dict[int, str]:
    names = await _load_group_member_names(context)
    missing_ids = [user_id for user_id in user_ids if user_id not in names]
    if missing_ids:
        names.update(await _load_qq_names(context, missing_ids))
    return names


async def execute(args: list[str], context: CommandContext) -> None:
    """处理 /lsadmin。"""

    _ = args
    admins = [
        qq for qq in context.config.admin_qqs if qq != context.config.superadmin_qq
    ]
    all_admins = [context.config.superadmin_qq, *admins]
    admin_names = await _resolve_admin_names(context, all_admins)

    lines = [
        "👑 超级管理员: "
        f"{admin_names.get(context.config.superadmin_qq, _UNKNOWN_MEMBER_NAME)}"
    ]
    if admins:
        admin_list = "\n".join(
            [
                f"- {admin_names.get(admin_qq, _UNKNOWN_MEMBER_NAME)}"
                for admin_qq in admins
            ]
        )
        lines.append(f"\n📋 管理员列表：\n{admin_list}")
    else:
        lines.append("\n📋 暂无其他管理员")
    await context.sender.send_group_message(context.group_id, "\n".join(lines))
