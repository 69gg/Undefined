from __future__ import annotations

from Undefined.config import get_config


def _normalize_base_url(value: str, fallback: str) -> str:
    base_url = value.strip().rstrip("/")
    return base_url or fallback.rstrip("/")


def build_url(base_url: str, path: str) -> str:
    normalized_path = path if path.startswith("/") else f"/{path}"
    return f"{base_url.rstrip('/')}{normalized_path}"


def get_request_timeout(default_timeout: float = 15.0) -> float:
    config = get_config(strict=False)
    timeout = float(config.network_request_timeout)
    return timeout if timeout > 0 else default_timeout


def get_request_retries(default_retries: int = 0) -> int:
    config = get_config(strict=False)
    retries = int(config.network_request_retries)
    if retries < 0:
        return default_retries
    return retries


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
