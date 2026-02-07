"""命令模块注册与上下文定义。"""

from Undefined.services.commands.context import CommandContext
from Undefined.services.commands.registry import CommandMeta, CommandRegistry

__all__ = ["CommandContext", "CommandMeta", "CommandRegistry"]
