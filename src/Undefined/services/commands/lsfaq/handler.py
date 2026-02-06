from __future__ import annotations

from Undefined.services.commands.context import CommandContext


async def execute(args: list[str], context: CommandContext) -> None:
    """处理 /lsfaq。"""

    _ = args
    await context.dispatcher._handle_lsfaq(context.group_id)
