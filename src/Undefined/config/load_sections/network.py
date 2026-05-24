"""Load network config section."""

from __future__ import annotations

# 配置分段加载：按 table 解析 TOML → ctx 字段 dict

import logging
import os
from pathlib import Path
from typing import Any, Optional

from ..coercers import (
    _coerce_bool,
    _coerce_float,
    _coerce_int,
    _coerce_str,
    _get_value,
    _normalize_base_url,
    _warn_env_fallback,
)

logger = logging.getLogger(__name__)


def load_network(
    data: dict[str, Any], *, config_path: Optional[Path] = None
) -> dict[str, Any]:
    searxng_url = _coerce_str(
        _get_value(data, ("search", "searxng_url"), "SEARXNG_URL"), ""
    )
    grok_search_enabled = _coerce_bool(
        _get_value(
            data,
            ("search", "grok_search_enabled"),
            "GROK_SEARCH_ENABLED",
        ),
        False,
    )

    use_proxy = _coerce_bool(
        _get_value(data, ("proxy", "use_proxy"), "USE_PROXY"), True
    )
    http_proxy = _coerce_str(
        _get_value(data, ("proxy", "http_proxy"), "http_proxy"), ""
    )
    # TOML 未配置时回退标准 HTTP_PROXY 环境变量（小写键名不走 ENV_REGISTRY）
    if not http_proxy:
        http_proxy = _coerce_str(os.getenv("HTTP_PROXY"), "")
        if http_proxy:
            _warn_env_fallback("HTTP_PROXY")
    https_proxy = _coerce_str(
        _get_value(data, ("proxy", "https_proxy"), "https_proxy"), ""
    )
    if not https_proxy:
        https_proxy = _coerce_str(os.getenv("HTTPS_PROXY"), "")
        if https_proxy:
            _warn_env_fallback("HTTPS_PROXY")

    network_request_timeout = _coerce_float(
        _get_value(
            data,
            ("network", "request_timeout_seconds"),
            "NETWORK_REQUEST_TIMEOUT_SECONDS",
        ),
        30.0,
    )
    if network_request_timeout <= 0:
        network_request_timeout = 480.0

    network_request_retries = _coerce_int(
        _get_value(
            data,
            ("network", "request_retries"),
            "NETWORK_REQUEST_RETRIES",
        ),
        0,
    )
    if network_request_retries < 0:
        network_request_retries = 0
    if network_request_retries > 5:
        network_request_retries = 5

    render_browser_max_concurrency = max(
        0,
        _coerce_int(
            _get_value(
                data,
                ("render", "browser_max_concurrency"),
                "RENDER_BROWSER_MAX_CONCURRENCY",
            ),
            0,
        ),
    )

    api_xxapi_base_url = _normalize_base_url(
        _coerce_str(
            _get_value(data, ("api_endpoints", "xxapi_base_url"), "XXAPI_BASE_URL"),
            "https://v2.xxapi.cn",
        ),
        "https://v2.xxapi.cn",
    )
    api_xingzhige_base_url = _normalize_base_url(
        _coerce_str(
            _get_value(
                data,
                ("api_endpoints", "xingzhige_base_url"),
                "XINGZHIGE_BASE_URL",
            ),
            "https://api.xingzhige.com",
        ),
        "https://api.xingzhige.com",
    )
    api_jkyai_base_url = _normalize_base_url(
        _coerce_str(
            _get_value(data, ("api_endpoints", "jkyai_base_url"), "JKYAI_BASE_URL"),
            "https://api.jkyai.top",
        ),
        "https://api.jkyai.top",
    )
    api_seniverse_base_url = _normalize_base_url(
        _coerce_str(
            _get_value(
                data,
                ("api_endpoints", "seniverse_base_url"),
                "SENIVERSE_BASE_URL",
            ),
            "https://api.seniverse.com/v3",
        ),
        "https://api.seniverse.com/v3",
    )

    weather_api_key = _coerce_str(
        _get_value(data, ("weather", "api_key"), "WEATHER_API_KEY"), ""
    )
    xxapi_api_token = _coerce_str(
        _get_value(data, ("xxapi", "api_token"), "XXAPI_API_TOKEN"), ""
    )

    mcp_config_path = _coerce_str(
        _get_value(data, ("mcp", "config_path"), "MCP_CONFIG_PATH"),
        "config/mcp.json",
    )

    # Bilibili 配置
    return {
        "searxng_url": searxng_url,
        "grok_search_enabled": grok_search_enabled,
        "use_proxy": use_proxy,
        "http_proxy": http_proxy,
        "https_proxy": https_proxy,
        "network_request_timeout": network_request_timeout,
        "network_request_retries": network_request_retries,
        "render_browser_max_concurrency": render_browser_max_concurrency,
        "api_xxapi_base_url": api_xxapi_base_url,
        "api_xingzhige_base_url": api_xingzhige_base_url,
        "api_jkyai_base_url": api_jkyai_base_url,
        "api_seniverse_base_url": api_seniverse_base_url,
        "weather_api_key": weather_api_key,
        "xxapi_api_token": xxapi_api_token,
        "mcp_config_path": mcp_config_path,
    }
