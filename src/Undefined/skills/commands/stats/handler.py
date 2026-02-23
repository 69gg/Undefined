from __future__ import annotations

from Undefined.services.commands.context import CommandContext


async def execute(args: list[str], context: CommandContext) -> None:
    """处理 /stats。"""

    if args and args[0] == "--help":
        await context.dispatcher._handle_stats_help(context.group_id)
        return
    await context.dispatcher._handle_stats(context.group_id, context.sender_id, args)
