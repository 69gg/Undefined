from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from typing import Any

from aiohttp import ClientSession, ClientTimeout, web
from aiohttp.web_response import Response

from Undefined.config import get_config
from ._shared import check_auth, routes

_AUTH_HEADER = "X-Undefined-API-Key"


def _runtime_base_url() -> str:
    cfg = get_config(strict=False)
    return f"http://{cfg.api.host}:{cfg.api.port}".rstrip("/")


def _unauthorized() -> Response:
    return web.json_response({"error": "Unauthorized"}, status=401)


def _runtime_disabled() -> Response:
    return web.json_response({"error": "Runtime API disabled"}, status=503)


async def _proxy_runtime(
    *,
    method: str,
    path: str,
    params: Mapping[str, str] | None = None,
    payload: dict[str, Any] | None = None,
) -> Response:
    cfg = get_config(strict=False)
    if not cfg.api.enabled:
        return _runtime_disabled()

    url = f"{_runtime_base_url()}{path}"
    timeout = ClientTimeout(total=20)
    headers = {_AUTH_HEADER: str(cfg.api.auth_key or "")}

    try:
        async with ClientSession(timeout=timeout) as session:
            async with session.request(
                method=method,
                url=url,
                params=params,
                json=payload,
                headers=headers,
            ) as resp:
                text = await resp.text()
                content_type = (resp.headers.get("Content-Type") or "").lower()
                if "application/json" in content_type:
                    try:
                        data = json.loads(text) if text else {}
                    except json.JSONDecodeError:
                        data = {"raw": text}
                    return web.json_response(data, status=resp.status)
                return web.Response(
                    status=resp.status,
                    text=text,
                    content_type=resp.content_type,
                    charset=resp.charset,
                )
    except (OSError, asyncio.TimeoutError) as exc:
        return web.json_response(
            {"error": "Runtime API unreachable", "detail": str(exc)},
            status=502,
        )


@routes.get("/api/runtime/meta")
async def runtime_meta_handler(request: web.Request) -> Response:
    if not check_auth(request):
        return _unauthorized()
    cfg = get_config(strict=False)
    return web.json_response(
        {
            "enabled": bool(cfg.api.enabled),
            "host": cfg.api.host,
            "port": cfg.api.port,
            "openapi_enabled": bool(cfg.api.openapi_enabled),
        }
    )


@routes.get("/api/runtime/openapi")
async def runtime_openapi_handler(request: web.Request) -> Response:
    if not check_auth(request):
        return _unauthorized()
    return await _proxy_runtime(
        method="GET",
        path="/openapi.json",
    )


@routes.get("/api/runtime/probes/internal")
async def runtime_probe_internal_handler(request: web.Request) -> Response:
    if not check_auth(request):
        return _unauthorized()
    return await _proxy_runtime(method="GET", path="/api/v1/probes/internal")


@routes.get("/api/runtime/probes/external")
async def runtime_probe_external_handler(request: web.Request) -> Response:
    if not check_auth(request):
        return _unauthorized()
    return await _proxy_runtime(method="GET", path="/api/v1/probes/external")


@routes.get("/api/runtime/memory")
async def runtime_memory_handler(request: web.Request) -> Response:
    if not check_auth(request):
        return _unauthorized()
    return await _proxy_runtime(
        method="GET",
        path="/api/v1/memory",
        params=request.query,
    )


@routes.get("/api/runtime/cognitive/events")
async def runtime_cognitive_events_handler(request: web.Request) -> Response:
    if not check_auth(request):
        return _unauthorized()
    return await _proxy_runtime(
        method="GET",
        path="/api/v1/cognitive/events",
        params=request.query,
    )


@routes.get("/api/runtime/cognitive/profiles")
async def runtime_cognitive_profiles_handler(request: web.Request) -> Response:
    if not check_auth(request):
        return _unauthorized()
    return await _proxy_runtime(
        method="GET",
        path="/api/v1/cognitive/profiles",
        params=request.query,
    )


@routes.get("/api/runtime/cognitive/profile/{entity_type}/{entity_id}")
async def runtime_cognitive_profile_handler(request: web.Request) -> Response:
    if not check_auth(request):
        return _unauthorized()
    entity_type = request.match_info.get("entity_type", "")
    entity_id = request.match_info.get("entity_id", "")
    return await _proxy_runtime(
        method="GET",
        path=f"/api/v1/cognitive/profile/{entity_type}/{entity_id}",
    )


@routes.post("/api/runtime/chat")
async def runtime_chat_handler(request: web.Request) -> Response:
    if not check_auth(request):
        return _unauthorized()
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    message = str(body.get("message", "") or "").strip()
    if not message:
        return web.json_response({"error": "message is required"}, status=400)

    return await _proxy_runtime(
        method="POST",
        path="/api/v1/chat",
        payload={"message": message},
    )
