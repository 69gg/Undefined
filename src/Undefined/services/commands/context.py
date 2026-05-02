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
    scope: str = "group"
    user_id: int | None = None
    is_webui_session: bool = False
    cognitive_service: Any = None
    history_manager: Any = None
    resolved_subcommand: str | None = None

    def check_permission(self, permission: str) -> bool:
        """统一权限检查入口，供 handler 内部提权场景使用。"""
        if permission == "superadmin":
            return self.config.is_superadmin(self.sender_id)
        if permission == "admin":
            return self.config.is_admin(self.sender_id) or self.config.is_superadmin(
                self.sender_id
            )
        return True
