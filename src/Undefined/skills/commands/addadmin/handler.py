from __future__ import annotations

import logging
from uuid import uuid4

from Undefined.services.commands.context import CommandContext

logger = logging.getLogger(__name__)


async def execute(args: list[str], context: CommandContext) -> None:
    """处理 /addadmin。"""

    if not args:
        await context.sender.send_group_message(
            context.group_id,
            "❌ 用法: /addadmin <QQ号>\n示例: /addadmin 123456789",
        )
        return

    try:
        new_admin_qq = int(args[0])
    except ValueError:
        await context.sender.send_group_message(
            context.group_id,
            "❌ QQ 号格式错误，必须为数字",
        )
        return

    if context.config.is_admin(new_admin_qq):
        await context.sender.send_group_message(
            context.group_id,
            f"⚠️ {new_admin_qq} 已经是管理员了",
        )
        return

    try:
        context.config.add_admin(new_admin_qq)
        await context.sender.send_group_message(
            context.group_id,
            f"✅ 已添加管理员: {new_admin_qq}",
        )
    except Exception as exc:
        error_id = uuid4().hex[:8]
        logger.exception("添加管理员失败: error_id=%s err=%s", error_id, exc)
        await context.sender.send_group_message(
            context.group_id,
            f"❌ 添加管理员失败，请稍后重试（错误码: {error_id}）",
        )
