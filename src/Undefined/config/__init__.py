"""配置模块"""

from typing import Optional

from .loader import Config
from .models import (
    AgentModelConfig,
    ChatModelConfig,
    SecurityModelConfig,
    VisionModelConfig,
)

__all__ = [
    "Config",
    "ChatModelConfig",
    "VisionModelConfig",
    "SecurityModelConfig",
    "AgentModelConfig",
    "get_config",
]

# 全局配置实例
_config: Optional[Config] = None


def get_config() -> Config:
    """获取配置实例（单例模式）"""
    global _config
    if _config is None:
        _config = Config.load()
    return _config
