from __future__ import annotations

from Undefined.config.naga_policy import (
    is_naga_gateway_active_for_group,
    is_naga_gateway_active_for_private,
)
from Undefined.services.commands.context import CommandContext


def is_naga_group_visible(context: CommandContext) -> bool:
    if context.scope != "group":
        return False
    return is_naga_gateway_active_for_group(context.config, int(context.group_id))


def is_naga_command_visible(context: CommandContext) -> bool:
    if context.scope == "group":
        return is_naga_group_visible(context)
    if context.scope == "private":
        user_id = context.user_id if context.user_id is not None else context.sender_id
        return is_naga_gateway_active_for_private(context.config, int(user_id))
    return False


def is_command_visible(context: CommandContext) -> bool:
    return is_naga_command_visible(context)
