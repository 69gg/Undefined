"""配置模型定义"""

from dataclasses import dataclass


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
    deepseek_new_cot_support: bool = False  # DeepSeek thinking-mode 工具调用兼容


@dataclass
class VisionModelConfig:
    """视觉模型配置"""

    api_url: str
    api_key: str
    model_name: str
    queue_interval_seconds: float = 1.0
    thinking_enabled: bool = False  # 是否启用 thinking
    thinking_budget_tokens: int = 20000  # 思维预算 token 数量
    deepseek_new_cot_support: bool = False  # DeepSeek thinking-mode 工具调用兼容


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
    deepseek_new_cot_support: bool = False  # DeepSeek thinking-mode 工具调用兼容


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
    deepseek_new_cot_support: bool = False  # DeepSeek thinking-mode 工具调用兼容
