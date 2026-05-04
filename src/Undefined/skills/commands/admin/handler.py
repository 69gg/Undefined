from __future__ import annotations

import asyncio
import logging
from typing import Any
from uuid import uuid4

from Undefined.services.commands.context import CommandContext

logger = logging.getLogger(__name__)

_UNKNOWN_MEMBER_NAME = "未知成员"

_USAGE_TEXT = (
    "用法：/admin [ls|add|del] [参数]\n"
    "子命令：ls（列表，管理员+）、add <QQ号|@用户>（添加，仅超管）、del <QQ号|@用户>（移除，仅超管）\n"
    "自动推断：无参数→ls"
)


async def _send(message: str, context: CommandContext) -> None:
    await context.sender.send_group_message(context.group_id, message)


# ── ls 相关 ──


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


async def _handle_ls(context: CommandContext) -> None:
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
    await _send("\n".join(lines), context)


# ── add 相关 ──


async def _handle_add(args: list[str], context: CommandContext) -> None:
    if not args:
        await _send(
            "❌ 用法: /admin add <QQ号|@用户>\n示例: /admin add 123456789 或 /admin add @某人",
            context,
        )
        return

    try:
        new_admin_qq = int(args[0])
    except ValueError:
        await _send("❌ QQ 号格式错误，必须为数字或 @ 提及", context)
        return

    if context.config.is_admin(new_admin_qq):
        await _send(f"⚠️ {new_admin_qq} 已经是管理员了", context)
        return

    try:
        context.config.add_admin(new_admin_qq)
        await _send(f"✅ 已添加管理员: {new_admin_qq}", context)
    except Exception as exc:
        error_id = uuid4().hex[:8]
        logger.exception("添加管理员失败: error_id=%s err=%s", error_id, exc)
        await _send(
            f"❌ 添加管理员失败，请稍后重试（错误码: {error_id}）",
            context,
        )


# ── del 相关 ──


async def _handle_del(args: list[str], context: CommandContext) -> None:
    if not args:
        await _send(
            "❌ 用法: /admin del <QQ号|@用户>\n示例: /admin del 123456789 或 /admin del @某人",
            context,
        )
        return

    try:
        target_qq = int(args[0])
    except ValueError:
        await _send("❌ QQ 号格式错误，必须为数字或 @ 提及", context)
        return

    if context.config.is_superadmin(target_qq):
        await _send("❌ 无法移除超级管理员", context)
        return

    if not context.config.is_admin(target_qq):
        await _send(f"⚠️ {target_qq} 不是管理员", context)
        return

    try:
        context.config.remove_admin(target_qq)
        await _send(f"✅ 已移除管理员: {target_qq}", context)
    except Exception as exc:
        error_id = uuid4().hex[:8]
        logger.exception("移除管理员失败: error_id=%s err=%s", error_id, exc)
        await _send(
            f"❌ 移除管理员失败，请稍后重试（错误码: {error_id}）",
            context,
        )


# ── 入口 ──


async def execute(args: list[str], context: CommandContext) -> None:
    """处理 /admin。分发层已处理子命令推断和权限检查，args 格式为 [子命令, *子参数]。"""
    if not args:
        await _handle_ls(context)
        return

    subcommand = args[0].lower()
    sub_args = args[1:]

    if subcommand == "ls":
        await _handle_ls(context)
    elif subcommand == "add":
        await _handle_add(sub_args, context)
    elif subcommand == "del":
        await _handle_del(sub_args, context)
    else:
        await _send(_USAGE_TEXT, context)
