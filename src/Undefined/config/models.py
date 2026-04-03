"""配置模型定义"""

from __future__ import annotations

from dataclasses import dataclass, field
from ipaddress import ip_address
from typing import Any


def format_netloc(host: str, port: int) -> str:
    """格式化 host:port 为合法 netloc，IPv6 地址自动加方括号。"""
    if ":" in host:
        return f"[{host}]:{port}"
    return f"{host}:{port}"


def resolve_bind_hosts(host: str) -> list[str]:
    """将监听地址展开为 aiohttp 绑定列表。

    Python asyncio 对 IPv6 socket 设置 ``IPV6_V6ONLY=1``，
    因此 ``::`` 只监听 IPv6。要实现双栈需同时绑定 IPv4 + IPv6。
    """
    if not host or host == "::":
        return ["0.0.0.0", "::"]
    return [host]


@dataclass
class ModelPoolEntry:
    """模型池中的单个模型条目（已合并缺省值后的完整配置）"""

    api_url: str
    api_key: str
    model_name: str
    max_tokens: int
    queue_interval_seconds: float = 1.0
    api_mode: str = "chat_completions"
    thinking_enabled: bool = False
    thinking_budget_tokens: int = 0
    thinking_include_budget: bool = True
    reasoning_effort_style: str = "openai"  # effort 传参风格：openai / anthropic
    thinking_tool_call_compat: bool = True
    responses_tool_choice_compat: bool = False
    responses_force_stateless_replay: bool = False
    prompt_cache_enabled: bool = True
    reasoning_enabled: bool = False
    reasoning_effort: str = "medium"
    request_params: dict[str, Any] = field(default_factory=dict)


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
    api_mode: str = "chat_completions"  # 请求 API 模式
    thinking_enabled: bool = False  # 是否启用 thinking
    thinking_budget_tokens: int = 20000  # 思维预算 token 数量
    thinking_include_budget: bool = True  # 是否在请求中发送 budget_tokens
    reasoning_effort_style: str = "openai"  # effort 传参风格：openai / anthropic
    thinking_tool_call_compat: bool = (
        True  # 思维链 + 工具调用兼容（本地回填 reasoning_content）
    )
    responses_tool_choice_compat: bool = (
        False  # Responses API 的 tool_choice 兼容模式（降级为字符串 required）
    )
    responses_force_stateless_replay: bool = False  # Responses API 续轮强制降级为 stateless replay（不使用 previous_response_id）
    prompt_cache_enabled: bool = True  # 是否启用自动 prompt_cache_key
    reasoning_enabled: bool = False  # 是否启用 reasoning.effort
    reasoning_effort: str = "medium"  # reasoning effort 档位
    request_params: dict[str, Any] = field(default_factory=dict)
    pool: ModelPool | None = None  # 模型池配置


@dataclass
class VisionModelConfig:
    """视觉模型配置"""

    api_url: str
    api_key: str
    model_name: str
    queue_interval_seconds: float = 1.0
    api_mode: str = "chat_completions"  # 请求 API 模式
    thinking_enabled: bool = False  # 是否启用 thinking
    thinking_budget_tokens: int = 20000  # 思维预算 token 数量
    thinking_include_budget: bool = True  # 是否在请求中发送 budget_tokens
    reasoning_effort_style: str = "openai"  # effort 传参风格：openai / anthropic
    thinking_tool_call_compat: bool = (
        True  # 思维链 + 工具调用兼容（本地回填 reasoning_content）
    )
    responses_tool_choice_compat: bool = (
        False  # Responses API 的 tool_choice 兼容模式（降级为字符串 required）
    )
    responses_force_stateless_replay: bool = False  # Responses API 续轮强制降级为 stateless replay（不使用 previous_response_id）
    prompt_cache_enabled: bool = True  # 是否启用自动 prompt_cache_key
    reasoning_enabled: bool = False  # 是否启用 reasoning.effort
    reasoning_effort: str = "medium"  # reasoning effort 档位
    request_params: dict[str, Any] = field(default_factory=dict)


@dataclass
class SecurityModelConfig:
    """安全模型配置（用于防注入检测和注入后的回复生成）"""

    api_url: str
    api_key: str
    model_name: str
    max_tokens: int
    queue_interval_seconds: float = 1.0
    api_mode: str = "chat_completions"  # 请求 API 模式
    thinking_enabled: bool = False  # 是否启用 thinking
    thinking_budget_tokens: int = 0  # 思维预算 token 数量
    thinking_include_budget: bool = True  # 是否在请求中发送 budget_tokens
    reasoning_effort_style: str = "openai"  # effort 传参风格：openai / anthropic
    thinking_tool_call_compat: bool = (
        True  # 思维链 + 工具调用兼容（本地回填 reasoning_content）
    )
    responses_tool_choice_compat: bool = (
        False  # Responses API 的 tool_choice 兼容模式（降级为字符串 required）
    )
    responses_force_stateless_replay: bool = False  # Responses API 续轮强制降级为 stateless replay（不使用 previous_response_id）
    prompt_cache_enabled: bool = True  # 是否启用自动 prompt_cache_key
    reasoning_enabled: bool = False  # 是否启用 reasoning.effort
    reasoning_effort: str = "medium"  # reasoning effort 档位
    request_params: dict[str, Any] = field(default_factory=dict)


@dataclass
class EmbeddingModelConfig:
    """嵌入模型配置"""

    api_url: str
    api_key: str
    model_name: str
    queue_interval_seconds: float = 0.0
    dimensions: int | None = None
    query_instruction: str = ""  # 查询端指令前缀（如 Qwen3-Embedding 需要）
    document_instruction: str = ""  # 文档端指令前缀（如 E5 系列需要 "passage: "）
    request_params: dict[str, Any] = field(default_factory=dict)


@dataclass
class RerankModelConfig:
    """重排模型配置"""

    api_url: str
    api_key: str
    model_name: str
    queue_interval_seconds: float = 0.0
    query_instruction: str = ""  # 查询端指令前缀（如部分 rerank 模型需要）
    request_params: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentModelConfig:
    """Agent 模型配置（用于执行 agents）"""

    api_url: str
    api_key: str
    model_name: str
    max_tokens: int = 4096
    queue_interval_seconds: float = 1.0
    api_mode: str = "chat_completions"  # 请求 API 模式
    thinking_enabled: bool = False  # 是否启用 thinking
    thinking_budget_tokens: int = 0  # 思维预算 token 数量
    thinking_include_budget: bool = True  # 是否在请求中发送 budget_tokens
    reasoning_effort_style: str = "openai"  # effort 传参风格：openai / anthropic
    thinking_tool_call_compat: bool = (
        True  # 思维链 + 工具调用兼容（本地回填 reasoning_content）
    )
    responses_tool_choice_compat: bool = (
        False  # Responses API 的 tool_choice 兼容模式（降级为字符串 required）
    )
    responses_force_stateless_replay: bool = False  # Responses API 续轮强制降级为 stateless replay（不使用 previous_response_id）
    prompt_cache_enabled: bool = True  # 是否启用自动 prompt_cache_key
    reasoning_enabled: bool = False  # 是否启用 reasoning.effort
    reasoning_effort: str = "medium"  # reasoning effort 档位
    request_params: dict[str, Any] = field(default_factory=dict)
    pool: ModelPool | None = None  # 模型池配置


@dataclass
class GrokModelConfig:
    """Grok 搜索模型配置（仅用于 grok_search）"""

    api_url: str
    api_key: str
    model_name: str
    max_tokens: int = 8192
    queue_interval_seconds: float = 1.0
    thinking_enabled: bool = False  # 是否启用 thinking
    thinking_budget_tokens: int = 20000  # 思维预算 token 数量
    thinking_include_budget: bool = True  # 是否在请求中发送 budget_tokens
    reasoning_effort_style: str = "openai"  # effort 传参风格：openai / anthropic
    prompt_cache_enabled: bool = True  # 是否启用自动 prompt_cache_key
    reasoning_enabled: bool = False  # 是否启用 reasoning.effort
    reasoning_effort: str = "medium"  # reasoning effort 档位
    request_params: dict[str, Any] = field(default_factory=dict)


@dataclass
class ImageGenModelConfig:
    """生图模型配置（放在 [models] 下，与 chat/vision 平级）

    空字符串 api_key/api_url 会在 handler 中降级到主模型配置。
    """

    api_url: str = ""
    api_key: str = ""
    model_name: str = ""
    request_params: dict[str, Any] = field(default_factory=dict)


@dataclass
class ImageGenConfig:
    """生图工具配置

    provider:
      - "xingzhige": 使用免费星之阁 API（api_xingzhige_base_url）
      - "models": 使用 [models.image_gen] 配置的 OpenAI 兼容接口

    OpenAI 兼容参数（openai_size/quality/style）空字符串不传，由上游 API 使用默认值。
    """

    # 生图 provider: "xingzhige" | "models"
    provider: str = "xingzhige"
    # xingzhige 模式下的默认图片比例
    xingzhige_size: str = "1:1"
    # models 模式下的 OpenAI 兼容参数（空字符串表示不传该字段）
    openai_size: str = ""
    openai_quality: str = ""
    openai_style: str = ""
    # models 模式请求超时（秒）
    openai_timeout: float = 120.0


@dataclass
class NagaConfig:
    """Naga 集成配置

    面向与 NagaAgent 对接的高级场景，普通用户不建议开启。

    开关分层：
    - ``features.nagaagent_mode_enabled`` — 控制 AI 侧行为（提示词切换、工具暴露）
    - ``naga.enabled`` — 控制外部网关集成（/naga、绑定回调、消息发送、解绑）

    两者均默认 False。可单独开启 ``nagaagent_mode_enabled`` 获得 NagaAgent 解答能力，
    无需启用外部回调联动。
    """

    enabled: bool = False
    api_url: str = ""
    api_key: str = ""
    moderation_enabled: bool = True
    allowed_groups: frozenset[int] = field(default_factory=frozenset)


@dataclass
class CognitiveConfig:
    """认知记忆系统配置"""

    enabled: bool = True
    # 史官改写时 bot 自身的称呼（仅影响认知记忆事件文本，不影响主提示词）
    bot_name: str = "Undefined"
    vector_store_path: str = "data/cognitive/chromadb"
    queue_path: str = "data/cognitive/queues"
    profiles_path: str = "data/cognitive/profiles"
    auto_top_k: int = 3
    # 自动注入检索时每个 scope 的候选扩展倍数（最终候选≈auto_top_k*该值）。
    # Candidate expansion multiplier per scope for auto retrieval (candidates ~= auto_top_k * this value).
    auto_scope_candidate_multiplier: int = 2
    # 群聊自动检索中，当前群命中条目的额外权重系数（>1 更偏向当前群）。
    # Extra score multiplier for current-group hits in group auto retrieval (>1 favors current group).
    auto_current_group_boost: float = 1.15
    # 私聊自动检索中，当前私聊命中条目的额外权重系数（>1 更偏向当前私聊）。
    # Extra score multiplier for current-private hits in private auto retrieval (>1 favors current private chat).
    auto_current_private_boost: float = 1.25
    enable_rerank: bool = True
    # When cognitive is enabled, also inject last N end action summaries as short-term working memory.
    # 0 disables this injection.
    recent_end_summaries_inject_k: int = 30
    time_decay_enabled: bool = True
    time_decay_half_life_days_auto: float = 14.0
    time_decay_half_life_days_tool: float = 60.0
    time_decay_boost: float = 0.2
    time_decay_min_similarity: float = 0.35
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
    job_max_retries: int = 3
    # Historian reference context shaping.
    # Number of recent messages attached to historian jobs for disambiguation.
    historian_recent_messages_inject_k: int = 12
    # Max characters per recent message line attached to historian jobs.
    historian_recent_message_line_max_len: int = 240
    # Max characters for the current source message attached to historian jobs.
    historian_source_message_max_len: int = 800


@dataclass
class MemeConfig:
    """表情包库配置。"""

    enabled: bool = True
    query_default_mode: str = "hybrid"
    max_source_image_bytes: int = 1024 * 1024
    blob_dir: str = "data/memes/blobs"
    preview_dir: str = "data/memes/previews"
    db_path: str = "data/memes/memes.sqlite3"
    vector_store_path: str = "data/memes/chromadb"
    queue_path: str = "data/memes/queues"
    max_items: int = 10000
    max_total_bytes: int = 5 * 1024 * 1024 * 1024
    allow_gif: bool = True
    auto_ingest_group: bool = True
    auto_ingest_private: bool = True
    keyword_top_k: int = 30
    semantic_top_k: int = 30
    rerank_top_k: int = 20


@dataclass
class APIConfig:
    """主进程 OpenAPI/Runtime API 配置"""

    enabled: bool = True
    host: str = "127.0.0.1"
    port: int = 8788
    auth_key: str = "changeme"
    openapi_enabled: bool = True
    tool_invoke_enabled: bool = False
    tool_invoke_expose: str = "tools+toolsets"
    tool_invoke_allowlist: list[str] = field(default_factory=list)
    tool_invoke_denylist: list[str] = field(default_factory=list)
    tool_invoke_timeout: int = 120
    tool_invoke_callback_timeout: int = 10

    @property
    def loopback_url(self) -> str:
        """同机代理用的回环 URL（通配地址映射到 127.0.0.1 / ::1）。"""
        host = self.host
        if not host:
            host = "127.0.0.1"
        else:
            try:
                addr = ip_address(host)
            except ValueError:
                pass  # 域名，原样
            else:
                if addr.is_unspecified:
                    host = "127.0.0.1" if addr.version == 4 else "::1"
        return f"http://{format_netloc(host, self.port)}"

    @property
    def display_url(self) -> str:
        """用于日志和展示的格式化 URL（保留原始 host，仅处理 IPv6 方括号）。"""
        return f"http://{format_netloc(self.host or '0.0.0.0', self.port)}"
