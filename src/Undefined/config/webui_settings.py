"""WebUI settings management."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from .coercers import _coerce_bool, _coerce_int, _coerce_str, _normalize_str, _get_value
from .env_registry import env_key_for_path

if TYPE_CHECKING:
    from .config_class import Config

DEFAULT_WEBUI_URL = "127.0.0.1"
DEFAULT_WEBUI_PORT = 8787
DEFAULT_WEBUI_PASSWORD = "changeme"
DEFAULT_WEBUI_AUTOSTART_BOT = False
DEFAULT_WEBUI_CHECK_UPDATES = True
DEFAULT_WEBUI_STOP_TIMEOUT_SECONDS = 0


@dataclass
class WebUISettings:
    url: str
    port: int
    password: str
    autostart_bot: bool
    check_updates: bool
    using_default_password: bool
    config_exists: bool
    stop_timeout_seconds: int = DEFAULT_WEBUI_STOP_TIMEOUT_SECONDS

    @classmethod
    def from_config(cls, config: Config, *, config_exists: bool) -> WebUISettings:
        """从已验证的 Config 构建运行时设置，不重新读取配置文件。"""
        password = config.webui_password or DEFAULT_WEBUI_PASSWORD
        return cls(
            url=config.webui_url,
            port=config.webui_port,
            password=password,
            autostart_bot=config.webui_autostart_bot,
            check_updates=config.webui_check_updates,
            using_default_password=password == DEFAULT_WEBUI_PASSWORD,
            config_exists=config_exists,
            stop_timeout_seconds=config.webui_stop_timeout_seconds,
        )

    @property
    def display_url(self) -> str:
        """用于日志和展示的格式化 URL。"""
        from Undefined.config.models import format_netloc

        return f"http://{format_netloc(self.url or '0.0.0.0', self.port)}"


def load_webui_settings(config_path: Optional[Path] = None) -> WebUISettings:
    from .loader import load_toml_data  # lazy to avoid circular

    return parse_webui_settings(load_toml_data(config_path))


def parse_webui_settings(data: dict[str, Any]) -> WebUISettings:
    """从已解析的配置构建 WebUI 设置，不再读取文件。"""
    config_exists = bool(data)
    url_value = _get_value(data, ("webui", "url"), None)
    port_value = _get_value(data, ("webui", "port"), None)
    password_value = _get_value(data, ("webui", "password"), None)
    autostart_bot_value = _get_value(data, ("webui", "autostart_bot"), None)
    check_updates_value = _get_value(data, ("webui", "check_updates"), None)

    url = _coerce_str(url_value, DEFAULT_WEBUI_URL)
    port = _coerce_int(port_value, DEFAULT_WEBUI_PORT)
    if port <= 0 or port > 65535:
        port = DEFAULT_WEBUI_PORT
    autostart_bot = _coerce_bool(autostart_bot_value, DEFAULT_WEBUI_AUTOSTART_BOT)
    check_updates = _coerce_bool(check_updates_value, DEFAULT_WEBUI_CHECK_UPDATES)
    stop_timeout_seconds = _coerce_int(
        _get_value(
            data,
            ("webui", "stop_timeout_seconds"),
            env_key_for_path(("webui", "stop_timeout_seconds")),
        ),
        DEFAULT_WEBUI_STOP_TIMEOUT_SECONDS,
    )
    if stop_timeout_seconds < 0:
        stop_timeout_seconds = DEFAULT_WEBUI_STOP_TIMEOUT_SECONDS

    password_normalized = _normalize_str(password_value)
    if not password_normalized:
        return WebUISettings(
            url=url,
            port=port,
            password=DEFAULT_WEBUI_PASSWORD,
            autostart_bot=autostart_bot,
            check_updates=check_updates,
            using_default_password=True,
            config_exists=config_exists,
            stop_timeout_seconds=stop_timeout_seconds,
        )
    return WebUISettings(
        url=url,
        port=port,
        password=password_normalized,
        autostart_bot=autostart_bot,
        check_updates=check_updates,
        using_default_password=password_normalized == DEFAULT_WEBUI_PASSWORD,
        config_exists=config_exists,
        stop_timeout_seconds=stop_timeout_seconds,
    )
