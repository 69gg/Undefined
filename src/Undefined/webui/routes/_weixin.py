"""Management WebUI 到 Runtime 微信管理 API 的鉴权代理。"""

from __future__ import annotations

import json
from urllib.parse import quote

from aiohttp import web
from aiohttp.web_response import Response

from ._runtime import _proxy_runtime, _proxy_runtime_binary
from ._shared import check_auth, routes


def _unauthorized() -> Response:
    return web.json_response({"error": "Unauthorized"}, status=401)


async def _body(request: web.Request) -> dict[str, object] | None:
    try:
        value = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


@routes.get("/api/v1/management/runtime/weixin")
async def management_weixin_status(request: web.Request) -> Response:
    if not check_auth(request):
        return _unauthorized()
    return await _proxy_runtime(method="GET", path="/api/v1/weixin")


@routes.post("/api/v1/management/runtime/weixin/login")
async def management_weixin_login_start(request: web.Request) -> Response:
    if not check_auth(request):
        return _unauthorized()
    payload = await _body(request)
    if payload is None:
        return web.json_response({"error": "Invalid JSON payload"}, status=400)
    return await _proxy_runtime(
        method="POST",
        path="/api/v1/weixin/login",
        payload=payload,
        timeout_seconds=30.0,
    )


@routes.get("/api/v1/management/runtime/weixin/login/{session_id}/qr.png")
async def management_weixin_login_qr(request: web.Request) -> Response:
    if not check_auth(request):
        return _unauthorized()
    session_id = quote(str(request.match_info.get("session_id", "")).strip(), safe="")
    response = await _proxy_runtime_binary(
        method="GET",
        path=f"/api/v1/weixin/login/{session_id}/qr.png",
    )
    response.headers["Cache-Control"] = "no-store, max-age=0"
    return response


@routes.post("/api/v1/management/runtime/weixin/login/{session_id}/refresh")
async def management_weixin_login_refresh(request: web.Request) -> Response:
    if not check_auth(request):
        return _unauthorized()
    session_id = quote(str(request.match_info.get("session_id", "")).strip(), safe="")
    return await _proxy_runtime(
        method="POST",
        path=f"/api/v1/weixin/login/{session_id}/refresh",
        payload={},
        timeout_seconds=30.0,
    )


@routes.post("/api/v1/management/runtime/weixin/login/{session_id}/verify")
async def management_weixin_login_verify(request: web.Request) -> Response:
    if not check_auth(request):
        return _unauthorized()
    payload = await _body(request)
    if payload is None:
        return web.json_response({"error": "Invalid JSON payload"}, status=400)
    session_id = quote(str(request.match_info.get("session_id", "")).strip(), safe="")
    return await _proxy_runtime(
        method="POST",
        path=f"/api/v1/weixin/login/{session_id}/verify",
        payload=payload,
    )


@routes.get("/api/v1/management/runtime/weixin/login/{session_id}")
async def management_weixin_login_poll(request: web.Request) -> Response:
    if not check_auth(request):
        return _unauthorized()
    session_id = quote(str(request.match_info.get("session_id", "")).strip(), safe="")
    return await _proxy_runtime(
        method="GET",
        path=f"/api/v1/weixin/login/{session_id}",
        timeout_seconds=30.0,
    )


@routes.delete("/api/v1/management/runtime/weixin/login/{session_id}")
async def management_weixin_login_cancel(request: web.Request) -> Response:
    if not check_auth(request):
        return _unauthorized()
    session_id = quote(str(request.match_info.get("session_id", "")).strip(), safe="")
    return await _proxy_runtime(
        method="DELETE",
        path=f"/api/v1/weixin/login/{session_id}",
    )


@routes.patch("/api/v1/management/runtime/weixin/accounts/{alias}")
async def management_weixin_account_update(request: web.Request) -> Response:
    if not check_auth(request):
        return _unauthorized()
    payload = await _body(request)
    if payload is None:
        return web.json_response({"error": "Invalid JSON payload"}, status=400)
    alias = quote(str(request.match_info.get("alias", "")).strip(), safe="")
    return await _proxy_runtime(
        method="PATCH",
        path=f"/api/v1/weixin/accounts/{alias}",
        payload=payload,
    )


@routes.delete("/api/v1/management/runtime/weixin/accounts/{alias}")
async def management_weixin_account_delete(request: web.Request) -> Response:
    if not check_auth(request):
        return _unauthorized()
    alias = quote(str(request.match_info.get("alias", "")).strip(), safe="")
    return await _proxy_runtime(
        method="DELETE",
        path=f"/api/v1/weixin/accounts/{alias}",
    )


@routes.get("/api/v1/management/runtime/weixin/pending")
async def management_weixin_pending_list(request: web.Request) -> Response:
    if not check_auth(request):
        return _unauthorized()
    return await _proxy_runtime(method="GET", path="/api/v1/weixin/pending")


@routes.delete("/api/v1/management/runtime/weixin/pending/{record_id}")
async def management_weixin_pending_delete(request: web.Request) -> Response:
    if not check_auth(request):
        return _unauthorized()
    record_id = quote(str(request.match_info.get("record_id", "")).strip(), safe="")
    return await _proxy_runtime(
        method="DELETE",
        path=f"/api/v1/weixin/pending/{record_id}",
    )


@routes.get("/api/v1/management/runtime/weixin/audit")
async def management_weixin_audit_list(request: web.Request) -> Response:
    if not check_auth(request):
        return _unauthorized()
    return await _proxy_runtime(
        method="GET",
        path="/api/v1/weixin/audit",
        params=request.query,
    )
