from __future__ import annotations

from Undefined.services.commands.context import CommandContext


async def execute(args: list[str], context: CommandContext) -> None:
    """处理 /help。"""

    _ = args
    commands = context.registry.list_commands(include_hidden=False)
    permission_label_map = {
        "public": "公开可用",
        "admin": "仅限管理员",
        "superadmin": "仅限超级管理员",
    }

    lines = ["Undefined命令模块 使用帮助", "", "可用命令：", ""]
    for item in commands:
        lines.append(item.usage)
        if item.description:
            lines.append(f"  {item.description}")
        if item.example and item.example != item.usage:
            lines.append(f"  示例：{item.example}")
        lines.append(f"  ({permission_label_map.get(item.permission, '公开可用')})")
        lines.append("")

    lines.append("© 由 Null(qq:1708213363) <pylindex@qq.com> 编写 版权所有")
    lines.append("开源链接：https://github.com/69gg/Undefined")
    await context.sender.send_group_message(context.group_id, "\n".join(lines))
