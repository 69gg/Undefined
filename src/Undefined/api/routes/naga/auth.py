"""Naga API 鉴权辅助。"""

from __future__ import annotations

import logging

from aiohttp import web

from Undefined.api._context import RuntimeAPIContext

logger = logging.getLogger(__name__)


# 校验 Naga 共享密钥，返回错误信息或 ``None`` 表示通过
def verify_naga_api_key(ctx: RuntimeAPIContext, request: web.Request) -> str | None:
    """校验 Naga 共享密钥，返回错误信息或 ``None`` 表示通过。"""
    import secrets as _secrets

    cfg = ctx.config_getter()
    expected = cfg.naga.api_key
    if not expected:
        return "naga api_key not configured"
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return "missing or invalid Authorization header"
    provided = auth_header[7:]
    # 常量时间比较，避免时序侧信道泄露密钥。
    if not _secrets.compare_digest(provided, expected):
        return "invalid api_key"
    return None
