"""OneBot WebSocket 客户端包。"""

# 统一 re-export，供 handlers 与 sender 直接 from Undefined.onebot import ...
from Undefined.onebot.client import OneBotClient
from Undefined.onebot.message import (
    get_message_content,
    get_message_sender_id,
    parse_message_time,
)

__all__ = [
    "OneBotClient",
    "parse_message_time",
    "get_message_sender_id",
    "get_message_content",
]
