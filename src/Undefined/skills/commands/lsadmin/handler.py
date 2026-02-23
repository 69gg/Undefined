from __future__ import annotations

from Undefined.services.commands.context import CommandContext


async def execute(args: list[str], context: CommandContext) -> None:
    """处理 /lsadmin。"""

    _ = args
    lines = [f"👑 超级管理员: {context.config.superadmin_qq}"]
    admins = [
        qq for qq in context.config.admin_qqs if qq != context.config.superadmin_qq
    ]
    if admins:
        admin_list = "\n".join([f"- {qq}" for qq in admins])
        lines.append(f"\n📋 管理员列表：\n{admin_list}")
    else:
        lines.append("\n📋 暂无其他管理员")
    await context.sender.send_group_message(context.group_id, "\n".join(lines))
