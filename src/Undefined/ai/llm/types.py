"""LLM 模块共享类型别名。"""

from __future__ import annotations

# 联合类型：所有可发起 LLM/嵌入/重排请求的模型配置
from Undefined.config import (
    AgentModelConfig,
    ChatModelConfig,
    EmbeddingModelConfig,
    GrokModelConfig,
    RerankModelConfig,
    SecurityModelConfig,
    VisionModelConfig,
)

ModelConfig = (
    ChatModelConfig
    | VisionModelConfig
    | AgentModelConfig
    | SecurityModelConfig
    | EmbeddingModelConfig
    | GrokModelConfig
    | RerankModelConfig
)

# 类型别名对外 re-export
__all__ = ["ModelConfig"]
