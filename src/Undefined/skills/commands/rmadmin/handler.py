from __future__ import annotations

import logging
from uuid import uuid4

from Undefined.services.commands.context import CommandContext

logger = logging.getLogger(__name__)


async def execute(args: list[str], context: CommandContext) -> None:
    """处理 /rmadmin。"""

    if not args:
        await context.sender.send_group_message(
            context.group_id,
            "❌ 用法: /rmadmin <QQ号>\n示例: /rmadmin 123456789",
        )
        return

    try:
        target_qq = int(args[0])
    except ValueError:
        await context.sender.send_group_message(
            context.group_id,
            "❌ QQ 号格式错误，必须为数字",
        )
        return

    if context.config.is_superadmin(target_qq):
        await context.sender.send_group_message(
            context.group_id, "❌ 无法移除超级管理员"
        )
        return

    if not context.config.is_admin(target_qq):
        await context.sender.send_group_message(
            context.group_id,
            f"⚠️ {target_qq} 不是管理员",
        )
        return

    try:
        context.config.remove_admin(target_qq)
        await context.sender.send_group_message(
            context.group_id,
            f"✅ 已移除管理员: {target_qq}",
        )
    except Exception as exc:
        error_id = uuid4().hex[:8]
        logger.exception("移除管理员失败: error_id=%s err=%s", error_id, exc)
        await context.sender.send_group_message(
            context.group_id,
            f"❌ 移除管理员失败，请稍后重试（错误码: {error_id}）",
        )
