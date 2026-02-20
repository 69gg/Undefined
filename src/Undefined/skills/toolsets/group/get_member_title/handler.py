from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from Undefined.context import RequestContext

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


def _snapshot_context(context: dict[str, Any]) -> dict[str, Any]:
    """冻结关键上下文，避免异步等待期间读取到漂移数据。"""
    ctx = RequestContext.current()

    group_id = context.get("group_id")
    request_id = context.get("request_id")

    if ctx is not None:
        if group_id is None:
            group_id = ctx.group_id
        if request_id is None:
            request_id = ctx.request_id

    return {
        "group_id": group_id,
        "request_id": request_id,
    }


def _resolve_onebot_client(context: dict[str, Any]) -> Any | None:
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


def _resolve_group_id(
    args: dict[str, Any], snapshot: dict[str, Any]
) -> tuple[int | None, str | None]:
    group_id_raw = args.get("group_id")
    if group_id_raw is None:
        group_id_raw = snapshot.get("group_id")
    if group_id_raw is None:
        return None, "请提供群号（group_id 参数），或者在群聊中调用"

    group_id, group_err = _parse_positive_int(group_id_raw, "group_id")
    if group_err or group_id is None:
        return None, group_err or "group_id 非法"
    return group_id, None


def _resolve_user_id(args: dict[str, Any]) -> tuple[int | None, str | None]:
    user_id_raw = args.get("user_id")
    qq_raw = args.get("qq")

    if user_id_raw is None and qq_raw is None:
        return None, "请提供要查询的群成员 QQ 号（user_id 或 qq 参数）"

    user_id, user_id_err = _parse_positive_int(user_id_raw, "user_id")
    qq, qq_err = _parse_positive_int(qq_raw, "qq")

    if user_id_raw is not None and user_id_err:
        return None, user_id_err
    if qq_raw is not None and qq_err:
        return None, qq_err

    if user_id is not None and qq is not None and user_id != qq:
        return None, "参数冲突：user_id 与 qq 不一致"

    resolved = user_id if user_id is not None else qq
    if resolved is None:
        return None, "请提供要查询的群成员 QQ 号（user_id 或 qq 参数）"
    return resolved, None


def _format_expire_time(raw_expire: Any) -> str:
    try:
        expire = int(raw_expire)
    except (TypeError, ValueError):
        return "未知"
    if expire == -1:
        return "永久"
    if expire <= 0:
        return "无"
    try:
        return datetime.fromtimestamp(expire).strftime("%Y-%m-%d %H:%M:%S")
    except (OSError, OverflowError, ValueError):
        return str(expire)


async def execute(args: dict[str, Any], context: dict[str, Any]) -> str:
    """获取指定群成员的群头衔信息。"""
    snapshot = _snapshot_context(context)
    request_id = str(snapshot.get("request_id") or "-")

    group_id, group_err = _resolve_group_id(args, snapshot)
    if group_err or group_id is None:
        return group_err or "group_id 非法"

    user_id, user_err = _resolve_user_id(args)
    if user_err or user_id is None:
        return user_err or "user_id 非法"

    no_cache = bool(args.get("no_cache", False))

    onebot_client = _resolve_onebot_client(context)
    if onebot_client is None:
        return "获取群头衔功能不可用（OneBot 客户端未设置）"

    try:
        member_info = await onebot_client.get_group_member_info(
            group_id, user_id, no_cache
        )
        if not member_info:
            return (
                f"未找到群 {group_id} 中 QQ {user_id} 的成员信息，"
                "可能该用户已退群、从未入群或群号不正确"
            )

        nickname = str(member_info.get("nickname") or "").strip()
        card = str(member_info.get("card") or "").strip()
        display_name = card or nickname or f"QQ{user_id}"

        title = str(member_info.get("title") or "").strip() or "无"
        title_expire_time = _format_expire_time(member_info.get("title_expire_time"))

        lines = [
            f"【群头衔】群号: {group_id}",
            f"成员: {display_name} (QQ: {user_id})",
            f"头衔: {title}",
            f"头衔过期时间: {title_expire_time}",
        ]
        return "\n".join(lines)

    except Exception as exc:
        logger.exception(
            "获取群头衔失败: group=%s user=%s request_id=%s err=%s",
            group_id,
            user_id,
            request_id,
            exc,
        )
        err_msg = str(exc)
        if "retcode=100" in err_msg:
            return "获取失败：群号或 QQ 号不存在"
        if "retcode=140" in err_msg:
            return "获取失败：无法获取该群成员头衔（权限不足）"
        if "retcode=150" in err_msg:
            return "获取失败：频率过高"
        return "获取失败：群头衔服务暂时不可用，请稍后重试"
