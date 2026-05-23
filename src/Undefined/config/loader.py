"""配置加载逻辑（向后兼容 shim；Config 实现见 config_class）。"""

from __future__ import annotations

from .admin import LOCAL_CONFIG_PATH, load_local_admins, save_local_admins
from .config_class import Config, ConfigBuilder
from .toml_io import CONFIG_PATH, load_toml_data
from .webui_settings import (
    DEFAULT_WEBUI_PASSWORD,
    DEFAULT_WEBUI_PORT,
    DEFAULT_WEBUI_URL,
    WebUISettings,
    load_webui_settings,
)

__all__ = [
    "CONFIG_PATH",
    "Config",
    "ConfigBuilder",
    "DEFAULT_WEBUI_PASSWORD",
    "DEFAULT_WEBUI_PORT",
    "DEFAULT_WEBUI_URL",
    "LOCAL_CONFIG_PATH",
    "WebUISettings",
    "load_local_admins",
    "load_toml_data",
    "load_webui_settings",
    "save_local_admins",
]
