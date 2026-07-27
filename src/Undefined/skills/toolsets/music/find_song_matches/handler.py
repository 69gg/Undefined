from __future__ import annotations

from typing import Any

from Undefined.skills.toolsets.music._tools import execute_find_song_matches


async def execute(args: dict[str, Any], context: dict[str, Any]) -> str:
    return await execute_find_song_matches(args, context)
