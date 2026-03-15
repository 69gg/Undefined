from __future__ import annotations

from Undefined.services.commands.context import CommandContext


def is_naga_group_visible(context: CommandContext) -> bool:
    if context.scope != "group":
        return False
    return int(context.group_id) in context.config.naga.allowed_groups


def is_naga_command_visible(context: CommandContext) -> bool:
    api_cfg = getattr(context.config, "api", None)
    if not bool(getattr(api_cfg, "enabled", False)):
        return False
    if not context.config.nagaagent_mode_enabled or not context.config.naga.enabled:
        return False
    if context.scope == "group":
        return is_naga_group_visible(context)
    if context.scope == "private":
        return context.config.is_superadmin(context.sender_id)
    return False
