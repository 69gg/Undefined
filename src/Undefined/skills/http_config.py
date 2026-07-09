from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from Undefined.config import get_config


def _normalize_base_url(value: str, fallback: str) -> str:
    base_url = value.strip().rstrip("/")
    return base_url or fallback.rstrip("/")


def build_url(base_url: str, path: str) -> str:
    normalized_path = path if path.startswith("/") else f"/{path}"
    return f"{base_url.rstrip('/')}{normalized_path}"


def get_request_timeout(default_timeout: float = 480.0) -> float:
    config = get_config(strict=False)
    timeout = float(config.network_request_timeout)
    return timeout if timeout > 0 else default_timeout


def get_request_retries(default_retries: int = 0) -> int:
    config = get_config(strict=False)
    retries = int(config.network_request_retries)
    if retries < 0:
        return default_retries
    return retries


def get_configured_proxy(
    url: str,
    *,
    use_proxy: bool,
    config: Any | None = None,
) -> str | None:
    if not use_proxy:
        return None

    if config is None:
        config = get_config(strict=False)
    http_proxy = str(getattr(config, "http_proxy", "") or "").strip()
    https_proxy = str(getattr(config, "https_proxy", "") or "").strip()
    scheme = urlsplit(url).scheme.lower()

    if scheme == "https":
        return https_proxy or http_proxy or None
    if scheme == "http":
        return http_proxy or https_proxy or None
    return https_proxy or http_proxy or None


def _scope_use_proxy(config: Any, proxy_scope: str) -> bool:
    scope = str(proxy_scope or "search").strip().lower()
    if scope.startswith("model:"):
        model_name = scope.split(":", 1)[1].strip().replace("-", "_")
        attr_name = "models_image_gen" if model_name == "image_gen" else None
        if model_name == "image_edit":
            attr_name = "models_image_edit"
        elif attr_name is None:
            attr_name = f"{model_name}_model"
        model_config = getattr(config, attr_name, None)
        return bool(getattr(model_config, "use_proxy", False))

    field_map = {
        "attachments": "attachment_use_proxy",
        "search": "search_use_proxy",
        "render": "render_use_proxy",
        "image_gen": "image_gen.use_proxy",
        "messages": "messages_use_proxy",
        "bilibili": "bilibili_use_proxy",
        "douyin": "douyin_use_proxy",
        "arxiv": "arxiv_use_proxy",
        "github": "github_use_proxy",
        "naga": "naga.use_proxy",
        "api_callback": "api.tool_invoke_callback_use_proxy",
    }
    field_path = field_map.get(scope)
    if not field_path:
        return False

    value: Any = config
    for part in field_path.split("."):
        value = getattr(value, part, None)
        if value is None:
            return False
    return bool(value)


def get_request_proxy(
    url: str,
    proxy_scope: str = "search",
    *,
    config: Any | None = None,
) -> str | None:
    if config is None:
        config = get_config(strict=False)
    return get_configured_proxy(
        url,
        use_proxy=_scope_use_proxy(config, proxy_scope),
        config=config,
    )


def build_httpx_client_kwargs(
    url: str,
    *,
    proxy_scope: str,
    timeout: Any | None = None,
    follow_redirects: bool | None = None,
    headers: dict[str, str] | None = None,
    cookies: Any | None = None,
    config: Any | None = None,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"trust_env": False}
    if timeout is not None:
        kwargs["timeout"] = timeout
    if follow_redirects is not None:
        kwargs["follow_redirects"] = follow_redirects
    if headers is not None:
        kwargs["headers"] = headers
    if cookies is not None:
        kwargs["cookies"] = cookies
    proxy = get_request_proxy(url, proxy_scope=proxy_scope, config=config)
    if proxy is not None:
        kwargs["proxy"] = proxy
    return kwargs


def get_xxapi_url(path: str) -> str:
    config = get_config(strict=False)
    base_url = _normalize_base_url(config.api_xxapi_base_url, "https://v2.xxapi.cn")
    return build_url(base_url, path)


def get_xingzhige_url(path: str) -> str:
    config = get_config(strict=False)
    base_url = _normalize_base_url(
        config.api_xingzhige_base_url,
        "https://api.xingzhige.com",
    )
    return build_url(base_url, path)


def get_jkyai_url(path: str) -> str:
    config = get_config(strict=False)
    base_url = _normalize_base_url(config.api_jkyai_base_url, "https://api.jkyai.top")
    return build_url(base_url, path)
