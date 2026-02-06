from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from Undefined.config import Config
from Undefined.faq import FAQStorage
from Undefined.onebot import OneBotClient
from Undefined.services.security import SecurityService
from Undefined.utils.sender import MessageSender

if TYPE_CHECKING:
    from Undefined.services.commands.registry import CommandRegistry


@dataclass
class CommandContext:
    """命令执行上下文。"""

    group_id: int
    sender_id: int
    config: Config
    sender: MessageSender
    ai: Any
    faq_storage: FAQStorage
    onebot: OneBotClient
    security: SecurityService
    queue_manager: Any
    rate_limiter: Any
    dispatcher: Any
    registry: CommandRegistry
