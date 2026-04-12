from __future__ import annotations

import logging

from Undefined import __version__
from Undefined.changelog import ChangelogError, get_latest_entry
from Undefined.services.commands.context import CommandContext

logger = logging.getLogger(__name__)


async def execute(args: list[str], context: CommandContext) -> None:
    """处理 /version（/v）。"""

    _ = args

    lines: list[str] = [f"Undefined v{__version__}"]

    try:
        entry = get_latest_entry()
        lines.append(f"    - {entry.title}")
    except ChangelogError:
        logger.warning("changelog 解析失败，跳过版本标题")
    except Exception:
        logger.exception("读取 changelog 时出现异常，跳过版本标题")

    message = "\n".join(lines)

    if context.scope == "private" and context.user_id is not None:
        await context.sender.send_private_message(context.user_id, message)
        return
    await context.sender.send_group_message(context.group_id, message)
