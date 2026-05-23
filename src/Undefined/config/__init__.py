"""配置模块"""

from typing import Optional

from .config_class import Config, ConfigBuilder
from .manager import ConfigManager
from .models import (
    APIConfig,
    AgentModelConfig,
    ChatModelConfig,
    EmbeddingModelConfig,
    GrokModelConfig,
    MemeConfig,
    MessageBatcherConfig,
    ModelPool,
    ModelPoolEntry,
    RenderCacheConfig,
    RerankModelConfig,
    SecurityModelConfig,
    VisionModelConfig,
)
from .webui_settings import WebUISettings, load_webui_settings

__all__ = [
    "Config",
    "ConfigBuilder",
    "ChatModelConfig",
    "VisionModelConfig",
    "SecurityModelConfig",
    "APIConfig",
    "AgentModelConfig",
    "EmbeddingModelConfig",
    "GrokModelConfig",
    "RerankModelConfig",
    "ModelPool",
    "ModelPoolEntry",
    "MemeConfig",
    "MessageBatcherConfig",
    "RenderCacheConfig",
    "get_config",
    "get_config_manager",
    "set_config",
    "load_webui_settings",
    "WebUISettings",
]

_config: Optional[Config] = None
_config_manager: Optional[ConfigManager] = None


def get_config_manager() -> ConfigManager:
    """获取全局配置管理器"""
    global _config_manager
    if _config_manager is None:
        _config_manager = ConfigManager()
    return _config_manager


def get_config(strict: bool = True) -> Config:
    """获取配置实例（单例模式）"""
    global _config
    if _config is None:
        _config = get_config_manager().load(strict=strict)
    return _config


def set_config(config: Config) -> None:
    """注入 Config 单例（库嵌入 opt-in；CLI / WebUI 启动链不得调用）。"""
    global _config
    _config = config
