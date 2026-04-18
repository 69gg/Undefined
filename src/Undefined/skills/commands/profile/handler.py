from __future__ import annotations

from Undefined.services.commands.context import CommandContext

_MAX_PROFILE_LENGTH = 3000


def _is_private(context: CommandContext) -> bool:
    return context.scope == "private"


def _truncate(text: str, limit: int = _MAX_PROFILE_LENGTH) -> str:
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "\n\n[侧写过长,已截断]"


async def _send(context: CommandContext, text: str) -> None:
    """Send message to appropriate channel."""
    if _is_private(context):
        user_id = int(context.user_id or context.sender_id)
        await context.sender.send_private_message(user_id, text)
    else:
        await context.sender.send_group_message(context.group_id, text)


async def execute(args: list[str], context: CommandContext) -> None:
    """处理 /profile 命令。"""
    cognitive_service = context.cognitive_service
    if cognitive_service is None:
        await _send(context, "❌ 侧写服务未启用")
        return

    # Parse subcommand: "g" or "group" → group profile
    sub = args[0].lower().strip() if args else ""

    if sub in ("group", "g"):
        if _is_private(context):
            await _send(context, "❌ 私聊中不支持查看群聊侧写")
            return
        entity_type = "group"
        entity_id = str(context.group_id)
        empty_hint = "暂无群聊侧写数据"
    else:
        entity_type = "user"
        entity_id = str(context.sender_id)
        empty_hint = "暂无侧写数据"

    profile = await cognitive_service.get_profile(entity_type, entity_id)
    if not profile:
        await _send(context, f"📭 {empty_hint}")
        return

    await _send(context, _truncate(profile))
