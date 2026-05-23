# 导入
from __future__ import annotations

# 导入
from urllib.parse import urlsplit

# 导入
from Undefined.config import get_config


# 函数 _normalize_base_url
def _normalize_base_url(value: str, fallback: str) -> str:
    # 赋值
    base_url = value.strip().rstrip("/")
    # 返回
    return base_url or fallback.rstrip("/")


# 函数 build_url
def build_url(base_url: str, path: str) -> str:
    # 赋值
    normalized_path = path if path.startswith("/") else f"/{path}"
    # 返回
    return f"{base_url.rstrip('/')}{normalized_path}"


# 函数 get_request_timeout
def get_request_timeout(default_timeout: float = 480.0) -> float:
    # 赋值
    config = get_config(strict=False)
    # 赋值
    timeout = float(config.network_request_timeout)
    # 返回
    return timeout if timeout > 0 else default_timeout


# 函数 get_request_retries
def get_request_retries(default_retries: int = 0) -> int:
    # 赋值
    config = get_config(strict=False)
    # 赋值
    retries = int(config.network_request_retries)
    # 条件分支
    if retries < 0:
        # 返回
        return default_retries
    # 返回
    return retries


# 函数 get_request_proxy
def get_request_proxy(url: str) -> str | None:
    # 赋值
    config = get_config(strict=False)
    # 条件分支
    if not bool(getattr(config, "use_proxy", False)):
        # 返回
        return None

    # 赋值
    http_proxy = str(getattr(config, "http_proxy", "") or "").strip()
    # 赋值
    https_proxy = str(getattr(config, "https_proxy", "") or "").strip()
    # 赋值
    scheme = urlsplit(url).scheme.lower()

    # 条件分支
    if scheme == "https":
        # 返回
        return https_proxy or http_proxy or None
    # 条件分支
    if scheme == "http":
        # 返回
        return http_proxy or https_proxy or None
    # 返回
    return https_proxy or http_proxy or None


# 函数 get_xxapi_url
def get_xxapi_url(path: str) -> str:
    # 赋值
    config = get_config(strict=False)
    # 赋值
    base_url = _normalize_base_url(config.api_xxapi_base_url, "https://v2.xxapi.cn")
    # 返回
    return build_url(base_url, path)


# 函数 get_xingzhige_url
def get_xingzhige_url(path: str) -> str:
    # 赋值
    config = get_config(strict=False)
    # 赋值
    base_url = _normalize_base_url(
        config.api_xingzhige_base_url,
        "https://api.xingzhige.com",
    )
    # 返回
    return build_url(base_url, path)


# 函数 get_jkyai_url
def get_jkyai_url(path: str) -> str:
    # 赋值
    config = get_config(strict=False)
    # 赋值
    base_url = _normalize_base_url(config.api_jkyai_base_url, "https://api.jkyai.top")
    # 返回
    return build_url(base_url, path)
