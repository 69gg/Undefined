"""WebUI settings management."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .coercers import _coerce_int, _coerce_str, _normalize_str, _get_value

DEFAULT_WEBUI_URL = "127.0.0.1"
DEFAULT_WEBUI_PORT = 8787
DEFAULT_WEBUI_PASSWORD = "changeme"


@dataclass
class WebUISettings:
    url: str
    port: int
    password: str
    using_default_password: bool
    config_exists: bool

    @property
    def display_url(self) -> str:
        """用于日志和展示的格式化 URL。"""
        from Undefined.config.models import format_netloc

        return f"http://{format_netloc(self.url or '0.0.0.0', self.port)}"


def load_webui_settings(config_path: Optional[Path] = None) -> WebUISettings:
    from .loader import load_toml_data  # lazy to avoid circular

    data = load_toml_data(config_path)
    config_exists = bool(data)
    url_value = _get_value(data, ("webui", "url"), None)
    port_value = _get_value(data, ("webui", "port"), None)
    password_value = _get_value(data, ("webui", "password"), None)

    url = _coerce_str(url_value, DEFAULT_WEBUI_URL)
    port = _coerce_int(port_value, DEFAULT_WEBUI_PORT)
    if port <= 0 or port > 65535:
        port = DEFAULT_WEBUI_PORT

    password_normalized = _normalize_str(password_value)
    if not password_normalized:
        return WebUISettings(
            url=url,
            port=port,
            password=DEFAULT_WEBUI_PASSWORD,
            using_default_password=True,
            config_exists=config_exists,
        )
    return WebUISettings(
        url=url,
        port=port,
        password=password_normalized,
        using_default_password=False,
        config_exists=config_exists,
    )
