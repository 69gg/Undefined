"""消息处理和命令分发包。

聚合 ``MessageHandler`` 与各 mixin 子模块；保留 ``parse_message_content_for_history`` 等
模块级符号供测试 monkeypatch（``import Undefined.handlers``）。
"""

from Undefined.handlers.message_flow import (
    KEYWORD_REPLY_HISTORY_PREFIX,
    MessageHandler,
)
from Undefined.handlers.poke import GroupPokeRecord, PrivatePokeRecord
from Undefined.handlers.repeat import REPEAT_REPLY_HISTORY_PREFIX
from Undefined.utils.common import (
    extract_text,
    matches_xinliweiyuan,
    parse_message_content_for_history,
)

__all__ = [
    "GroupPokeRecord",
    "KEYWORD_REPLY_HISTORY_PREFIX",
    "MessageHandler",
    "PrivatePokeRecord",
    "REPEAT_REPLY_HISTORY_PREFIX",
    "extract_text",
    "matches_xinliweiyuan",
    "parse_message_content_for_history",
]
