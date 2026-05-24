"""AI 客户端子包。

对外稳定入口：``AIClient``；导入路径 ``Undefined.ai.client`` 指向本子包。
"""

from Undefined.ai.client.ask_loop import ClientAskLoopMixin
from Undefined.ai.client.setup import (
    MISSING_TOOL_CALL_RETRY_HINT,
    SendMessageCallback,
    SendPrivateMessageCallback,
    _INVALID_TOOL_CALL_CONTENT,
    _build_invalid_tool_call_response,
    _resolve_summary_model_config,
)

# 会话消息拉取 helper，供 ask 与 slash 命令共用
from Undefined.services.message_summary_fetch import fetch_session_messages


# MRO：ClientAskLoopMixin → ClientQueueMixin → ClientSetupMixin，能力按 mixin 分层叠加
class AIClient(ClientAskLoopMixin):
    """AI 模型客户端。

    协调 Prompt 构建、队列化 LLM 请求、工具调用与多模态/摘要能力。
    """


__all__ = [
    "AIClient",
    "MISSING_TOOL_CALL_RETRY_HINT",
    "SendMessageCallback",
    "SendPrivateMessageCallback",
    "_INVALID_TOOL_CALL_CONTENT",
    "_build_invalid_tool_call_response",
    "_resolve_summary_model_config",
    "fetch_session_messages",
]
