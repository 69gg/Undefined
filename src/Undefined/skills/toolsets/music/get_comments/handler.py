from __future__ import annotations

from typing import Any

from Undefined.skills.toolsets.music._tools import execute_get_comments


async def execute(args: dict[str, Any], context: dict[str, Any]) -> str:
    return await execute_get_comments(args, context)
