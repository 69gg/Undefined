from __future__ import annotations

from Undefined.changelog import (
    ChangelogError,
    ChangelogFormatError,
    get_entry,
    get_latest_entry,
    list_entries,
)
from Undefined.services.commands.context import CommandContext

_DEFAULT_LIST_LIMIT = 8
_MAX_LIST_LIMIT = 20


def _parse_list_limit(raw: str | None) -> int:
    if raw is None or not str(raw).strip():
        return _DEFAULT_LIST_LIMIT
    try:
        parsed = int(str(raw).strip())
    except (TypeError, ValueError) as exc:
        raise ChangelogFormatError("数量必须是整数") from exc
    if parsed <= 0:
        raise ChangelogFormatError("数量必须大于 0")
    return min(parsed, _MAX_LIST_LIMIT)


def _format_entry_message(version: str | None = None) -> str:
    entry = get_latest_entry() if version is None else get_entry(version)
    lines = [
        f"{entry.version} {entry.title}",
        "",
        entry.summary,
        "",
        *[f"- {change}" for change in entry.changes],
    ]
    return "\n".join(lines)


def _format_list(limit: int) -> str:
    entries = list_entries(limit=limit)
    lines = [
        "Undefined CHANGELOG",
        "",
        *[f"- {entry.version} | {entry.title}" for entry in entries],
        "",
        "查看详情：/changelog show <version>",
    ]
    return "\n".join(lines)


async def execute(args: list[str], context: CommandContext) -> None:
    try:
        if not args:
            message = _format_list(_DEFAULT_LIST_LIMIT)
        else:
            subcommand = str(args[0]).strip().lower()
            if subcommand == "list":
                if len(args) > 2:
                    raise ChangelogFormatError("用法：/changelog list [数量]")
                limit = _parse_list_limit(args[1] if len(args) == 2 else None)
                message = _format_list(limit)
            elif subcommand == "show":
                if len(args) != 2:
                    raise ChangelogFormatError("用法：/changelog show <版本号>")
                message = _format_entry_message(args[1])
            elif subcommand == "latest":
                if len(args) != 1:
                    raise ChangelogFormatError("用法：/changelog latest")
                message = _format_entry_message()
            else:
                raise ChangelogFormatError(
                    "用法：/changelog [list [数量]|show <版本号>|latest]"
                )
    except (FileNotFoundError, ChangelogError) as exc:
        message = f"❌ {exc}"

    await context.sender.send_group_message(context.group_id, message)
