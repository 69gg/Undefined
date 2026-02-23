from __future__ import annotations

from Undefined.services.commands.context import CommandContext


async def execute(args: list[str], context: CommandContext) -> None:
    """处理 /stats。"""

    await context.dispatcher._handle_stats(context.group_id, context.sender_id, args)
