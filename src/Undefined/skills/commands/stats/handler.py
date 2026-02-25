from __future__ import annotations

from Undefined.services.commands.context import CommandContext


async def execute(args: list[str], context: CommandContext) -> None:
    """处理 /stats。"""
    if context.scope == "private":
        user_id = int(context.user_id or context.sender_id)
        send_private = getattr(context.sender, "send_private_message", None)
        send_message = None
        if callable(send_private):

            async def _send_message(message: str) -> None:
                await send_private(user_id, message)

            send_message = _send_message
        await context.dispatcher._handle_stats_private(
            user_id,
            context.sender_id,
            args,
            send_message=send_message,
            is_webui_session=bool(context.is_webui_session),
        )
        return

    await context.dispatcher._handle_stats(context.group_id, context.sender_id, args)
