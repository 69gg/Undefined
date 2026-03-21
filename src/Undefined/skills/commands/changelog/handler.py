from __future__ import annotations

from typing import Any

from Undefined.changelog import (
    ChangelogEntry,
    ChangelogError,
    ChangelogFormatError,
    get_entry,
    get_latest_entry,
    list_entries,
    normalize_version,
)
from Undefined.services.commands.context import CommandContext

_DEFAULT_LIST_LIMIT = 8
_FORWARD_LIST_THRESHOLD = 20
_FORWARD_NODE_BATCH_SIZE = 50
_USAGE_TEXT = "用法：/changelog [list [数量]|show <版本号>|latest|<版本号>|<数量>]"


def _parse_list_limit(raw: str | None) -> int:
    if raw is None or not str(raw).strip():
        return _DEFAULT_LIST_LIMIT
    try:
        parsed = int(str(raw).strip())
    except (TypeError, ValueError) as exc:
        raise ChangelogFormatError("数量必须是整数") from exc
    if parsed <= 0:
        raise ChangelogFormatError("数量必须大于 0")
    return parsed


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


def _format_list_entries(entries: tuple[ChangelogEntry, ...]) -> str:
    lines = [
        "Undefined CHANGELOG",
        "",
        *[f"- {entry.version} | {entry.title}" for entry in entries],
        "",
        "查看详情：/changelog <version> 或 /changelog show <version>",
    ]
    return "\n".join(lines)


def _format_list(limit: int) -> str:
    return _format_list_entries(list_entries(limit=limit))


def _build_list_forward_nodes(
    entries: tuple[ChangelogEntry, ...], *, bot_qq: int | str
) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    bot_uin = str(bot_qq)

    def _add_node(content: str) -> None:
        nodes.append(
            {
                "type": "node",
                "data": {"name": "Bot", "uin": bot_uin, "content": content},
            }
        )

    _add_node(
        "\n".join(
            [
                "Undefined CHANGELOG",
                f"共 {len(entries)} 个版本",
                "查看详情：/changelog <version> 或 /changelog show <version>",
            ]
        )
    )

    batch: list[str] = []
    for index, entry in enumerate(entries, start=1):
        batch.append(f"{index}. {entry.version} | {entry.title}")
        if len(batch) >= _FORWARD_NODE_BATCH_SIZE:
            _add_node("\n".join(batch))
            batch = []

    if batch:
        _add_node("\n".join(batch))

    return nodes


async def _send_list(limit: int, context: CommandContext) -> None:
    entries = list_entries(limit=limit)
    if (
        context.scope != "private"
        and context.group_id > 0
        and limit > _FORWARD_LIST_THRESHOLD
    ):
        bot_qq = getattr(context.config, "bot_qq", 0)
        forward_nodes = _build_list_forward_nodes(entries, bot_qq=bot_qq)
        await context.onebot.send_forward_msg(context.group_id, forward_nodes)
        return
    await _send_message(_format_list_entries(entries), context)


async def _send_message(message: str, context: CommandContext) -> None:
    if context.scope == "private" and context.user_id is not None:
        await context.sender.send_private_message(context.user_id, message)
        return
    await context.sender.send_group_message(context.group_id, message)


def _infer_single_argument(arg: str) -> tuple[str, str] | None:
    token = str(arg).strip()
    if not token:
        return None
    if token.isdigit():
        return ("list", token)
    try:
        normalize_version(token)
    except ChangelogFormatError:
        return None
    return ("show", token)


async def execute(args: list[str], context: CommandContext) -> None:
    try:
        if not args:
            await _send_list(_DEFAULT_LIST_LIMIT, context)
            return
        else:
            subcommand = str(args[0]).strip().lower()
            if subcommand == "list":
                if len(args) > 2:
                    raise ChangelogFormatError("用法：/changelog list [数量]")
                limit = _parse_list_limit(args[1] if len(args) == 2 else None)
                await _send_list(limit, context)
                return
            elif subcommand == "show":
                if len(args) != 2:
                    raise ChangelogFormatError("用法：/changelog show <版本号>")
                message = _format_entry_message(args[1])
            elif subcommand == "latest":
                if len(args) != 1:
                    raise ChangelogFormatError("用法：/changelog latest")
                message = _format_entry_message()
            else:
                inferred = _infer_single_argument(args[0]) if len(args) == 1 else None
                if inferred is None:
                    raise ChangelogFormatError(_USAGE_TEXT)
                action, value = inferred
                if action == "list":
                    await _send_list(_parse_list_limit(value), context)
                    return
                message = _format_entry_message(value)
    except (FileNotFoundError, ChangelogError) as exc:
        message = f"❌ {exc}"

    await _send_message(message, context)
