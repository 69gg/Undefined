"""配置模块"""

from typing import Optional

from .loader import Config, WebUISettings, load_webui_settings
from .manager import ConfigManager
from .models import (
    AgentModelConfig,
    ChatModelConfig,
    InflightSummaryModelConfig,
    ModelPool,
    ModelPoolEntry,
    SecurityModelConfig,
    VisionModelConfig,
)

__all__ = [
    "Config",
    "ChatModelConfig",
    "VisionModelConfig",
    "SecurityModelConfig",
    "AgentModelConfig",
    "InflightSummaryModelConfig",
    "ModelPool",
    "ModelPoolEntry",
    "get_config",
    "get_config_manager",
    "load_webui_settings",
    "WebUISettings",
]

# 全局配置实例
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
