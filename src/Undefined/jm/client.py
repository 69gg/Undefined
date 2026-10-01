"""jmcpy 客户端设置。

jmcpy 的接口与图片 CDN 都走 HTTPS，因此这里只按 scheme 取 ``[proxy]`` 里的代理，
再叠加 ``[jm]`` 的超时、并发与会话目录。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from jmcpy import Settings

from Undefined.skills.http_config import get_request_proxy

#: 仅用于按 scheme 选择代理地址（jmcpy 的请求全部是 HTTPS）
_PROXY_PROBE_URL = "https://18comic.vip"


def build_settings(config: Any) -> Settings:
    """把 ``[jm]`` 配置映射成 jmcpy 的 :class:`~jmcpy.Settings`。"""
    home = str(getattr(config, "jm_session_dir", "") or "").strip()
    return Settings(
        proxy=get_request_proxy(_PROXY_PROBE_URL, proxy_scope="jm", config=config),
        timeout=float(getattr(config, "jm_request_timeout", 20.0)),
        image_timeout=float(getattr(config, "jm_image_timeout", 60.0)),
        concurrency=int(getattr(config, "jm_download_concurrency", 8)),
        home=Path(home) if home else None,
    )
