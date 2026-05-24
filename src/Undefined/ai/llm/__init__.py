"""LLM 模型请求子包。

对外稳定入口：``ModelRequester``、``build_request_body``、``ModelConfig``。
"""

from Undefined.ai.llm.requester import ModelRequester, build_request_body
from Undefined.ai.llm.sanitize import _encode_tool_name_for_api
from Undefined.ai.llm.streaming import should_fallback_from_stream
from Undefined.ai.llm.types import ModelConfig

# 测试与内部调用沿用的私有符号别名（保持旧 import 路径可用）
_should_fallback_from_stream = should_fallback_from_stream

# 子包公开 API 列表
__all__ = [
    "ModelRequester",
    "build_request_body",
    "ModelConfig",
    "_encode_tool_name_for_api",
    "_should_fallback_from_stream",
]
