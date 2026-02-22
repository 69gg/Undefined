"""配置模型定义"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ModelPoolEntry:
    """模型池中的单个模型条目（已合并缺省值后的完整配置）"""

    api_url: str
    api_key: str
    model_name: str
    max_tokens: int
    queue_interval_seconds: float = 1.0
    thinking_enabled: bool = False
    thinking_budget_tokens: int = 0
    thinking_include_budget: bool = True
    thinking_tool_call_compat: bool = False


@dataclass
class ModelPool:
    """模型池配置"""

    enabled: bool = True  # 是否启用模型池功能
    strategy: str = "default"  # "default" | "round_robin" | "random"
    models: list[ModelPoolEntry] = field(default_factory=list)


@dataclass
class ChatModelConfig:
    """对话模型配置"""

    api_url: str
    api_key: str
    model_name: str
    max_tokens: int
    queue_interval_seconds: float = 1.0
    thinking_enabled: bool = False  # 是否启用 thinking
    thinking_budget_tokens: int = 20000  # 思维预算 token 数量
    thinking_include_budget: bool = True  # 是否在请求中发送 budget_tokens
    thinking_tool_call_compat: bool = (
        False  # 思维链 + 工具调用兼容（回传 reasoning_content）
    )
    pool: ModelPool | None = None  # 模型池配置


@dataclass
class VisionModelConfig:
    """视觉模型配置"""

    api_url: str
    api_key: str
    model_name: str
    queue_interval_seconds: float = 1.0
    thinking_enabled: bool = False  # 是否启用 thinking
    thinking_budget_tokens: int = 20000  # 思维预算 token 数量
    thinking_include_budget: bool = True  # 是否在请求中发送 budget_tokens
    thinking_tool_call_compat: bool = (
        False  # 思维链 + 工具调用兼容（回传 reasoning_content）
    )


@dataclass
class SecurityModelConfig:
    """安全模型配置（用于防注入检测和注入后的回复生成）"""

    api_url: str
    api_key: str
    model_name: str
    max_tokens: int
    queue_interval_seconds: float = 1.0
    thinking_enabled: bool = False  # 是否启用 thinking
    thinking_budget_tokens: int = 0  # 思维预算 token 数量
    thinking_include_budget: bool = True  # 是否在请求中发送 budget_tokens
    thinking_tool_call_compat: bool = (
        False  # 思维链 + 工具调用兼容（回传 reasoning_content）
    )


@dataclass
class EmbeddingModelConfig:
    """嵌入模型配置"""

    api_url: str
    api_key: str
    model_name: str
    queue_interval_seconds: float = 1.0
    dimensions: int | None = None
    query_instruction: str = ""  # 查询端指令前缀（如 Qwen3-Embedding 需要）
    document_instruction: str = ""  # 文档端指令前缀（如 E5 系列需要 "passage: "）


@dataclass
class RerankModelConfig:
    """重排模型配置"""

    api_url: str
    api_key: str
    model_name: str
    queue_interval_seconds: float = 1.0
    query_instruction: str = ""  # 查询端指令前缀（如部分 rerank 模型需要）


@dataclass
class AgentModelConfig:
    """Agent 模型配置（用于执行 agents）"""

    api_url: str
    api_key: str
    model_name: str
    max_tokens: int = 4096
    queue_interval_seconds: float = 1.0
    thinking_enabled: bool = False  # 是否启用 thinking
    thinking_budget_tokens: int = 0  # 思维预算 token 数量
    thinking_include_budget: bool = True  # 是否在请求中发送 budget_tokens
    thinking_tool_call_compat: bool = (
        False  # 思维链 + 工具调用兼容（回传 reasoning_content）
    )
    pool: ModelPool | None = None  # 模型池配置


@dataclass
class CognitiveConfig:
    """认知记忆系统配置"""

    enabled: bool = True
    vector_store_path: str = "data/cognitive/chromadb"
    queue_path: str = "data/cognitive/queues"
    profiles_path: str = "data/cognitive/profiles"
    auto_top_k: int = 3
    tool_default_top_k: int = 12
    profile_top_k: int = 8
    rewrite_max_retry: int = 2
    poll_interval_seconds: float = 1.0
    stale_job_timeout_seconds: float = 300.0
    profile_revision_keep: int = 5
    failed_max_age_days: int = 30
    failed_max_files: int = 500
    failed_cleanup_interval: int = 100
    rerank_candidate_multiplier: int = 3
