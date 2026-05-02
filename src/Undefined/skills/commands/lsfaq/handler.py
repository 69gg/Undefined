from __future__ import annotations

from Undefined.services.commands.context import CommandContext
from Undefined.skills.commands.faq.handler import execute as execute_faq


async def execute(args: list[str], context: CommandContext) -> None:
    await execute_faq(["ls", *args], context)
