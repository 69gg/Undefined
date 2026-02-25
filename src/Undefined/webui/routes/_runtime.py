from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from aiohttp import ClientSession, ClientTimeout, web
from aiohttp.web_response import Response

from Undefined.config import get_config
from Undefined.utils.paths import CACHE_DIR
from ._shared import check_auth, routes

_AUTH_HEADER = "X-Undefined-API-Key"
_CHAT_PROXY_TIMEOUT_SECONDS = 480.0
_MAX_CHAT_IMAGE_SIZE = 12 * 1024 * 1024
_ALLOWED_CHAT_IMAGE_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".bmp",
}


def _runtime_base_url() -> str:
    cfg = get_config(strict=False)
    return f"http://{cfg.api.host}:{cfg.api.port}".rstrip("/")


def _unauthorized() -> Response:
    return web.json_response({"error": "Unauthorized"}, status=401)


def _runtime_disabled() -> Response:
    return web.json_response({"error": "Runtime API disabled"}, status=503)


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    text = str(value or "").strip().lower()
    return text in {"1", "true", "yes", "on"}


def _resolve_chat_image_path(raw_path: str) -> Path | None:
    text = str(raw_path or "").strip()
    if not text:
        return None

    path = Path(text).expanduser()
    if not path.is_absolute():
        path = (Path.cwd() / path).resolve()
    else:
        path = path.resolve()

    cache_root = (Path.cwd() / CACHE_DIR).resolve()
    if path != cache_root and cache_root not in path.parents:
        return None
    if path.suffix.lower() not in _ALLOWED_CHAT_IMAGE_EXTENSIONS:
        return None
    if not path.is_file():
        return None
    if path.stat().st_size > _MAX_CHAT_IMAGE_SIZE:
        return None
    return path


async def _proxy_runtime(
    *,
    method: str,
    path: str,
    params: Mapping[str, str] | None = None,
    payload: dict[str, Any] | None = None,
    timeout_seconds: float = 20.0,
) -> Response:
    cfg = get_config(strict=False)
    if not cfg.api.enabled:
        return _runtime_disabled()

    url = f"{_runtime_base_url()}{path}"
    timeout = ClientTimeout(total=timeout_seconds)
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


async def _proxy_runtime_stream(
    request: web.Request,
    *,
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    timeout_seconds: float = _CHAT_PROXY_TIMEOUT_SECONDS,
) -> web.StreamResponse:
    cfg = get_config(strict=False)
    if not cfg.api.enabled:
        return _runtime_disabled()

    url = f"{_runtime_base_url()}{path}"
    timeout = ClientTimeout(total=timeout_seconds)
    headers = {_AUTH_HEADER: str(cfg.api.auth_key or "")}
    accept = request.headers.get("Accept")
    if accept:
        headers["Accept"] = accept

    try:
        async with ClientSession(timeout=timeout) as session:
            async with session.request(
                method=method,
                url=url,
                json=payload,
                headers=headers,
            ) as upstream:
                content_type = (upstream.headers.get("Content-Type") or "").lower()
                if "text/event-stream" not in content_type:
                    text = await upstream.text()
                    if "application/json" in content_type:
                        try:
                            data = json.loads(text) if text else {}
                        except json.JSONDecodeError:
                            data = {"raw": text}
                        return web.json_response(data, status=upstream.status)
                    return web.Response(
                        status=upstream.status,
                        text=text,
                        content_type=upstream.content_type,
                        charset=upstream.charset,
                    )

                downstream = web.StreamResponse(
                    status=upstream.status,
                    reason=upstream.reason,
                    headers={
                        "Content-Type": "text/event-stream",
                        "Cache-Control": "no-cache",
                        "Connection": "keep-alive",
                    },
                )
                await downstream.prepare(request)
                try:
                    async for chunk in upstream.content.iter_chunked(1024):
                        if request.transport is None or request.transport.is_closing():
                            break
                        await downstream.write(chunk)
                except (ConnectionResetError, RuntimeError):
                    pass
                finally:
                    try:
                        await downstream.write_eof()
                    except Exception:
                        pass
                return downstream
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
async def runtime_chat_handler(request: web.Request) -> web.StreamResponse:
    if not check_auth(request):
        return _unauthorized()
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    message = str(body.get("message", "") or "").strip()
    if not message:
        return web.json_response({"error": "message is required"}, status=400)

    stream = _to_bool(body.get("stream"))
    payload: dict[str, Any] = {"message": message}
    if stream:
        payload["stream"] = True
        return await _proxy_runtime_stream(
            request,
            method="POST",
            path="/api/v1/chat",
            payload=payload,
            timeout_seconds=_CHAT_PROXY_TIMEOUT_SECONDS,
        )

    return await _proxy_runtime(
        method="POST",
        path="/api/v1/chat",
        payload=payload,
        timeout_seconds=_CHAT_PROXY_TIMEOUT_SECONDS,
    )


@routes.get("/api/runtime/chat/history")
async def runtime_chat_history_handler(request: web.Request) -> Response:
    if not check_auth(request):
        return _unauthorized()
    return await _proxy_runtime(
        method="GET",
        path="/api/v1/chat/history",
        params=request.query,
    )


@routes.get("/api/runtime/chat/image")
async def runtime_chat_image_handler(request: web.Request) -> web.StreamResponse:
    if not check_auth(request):
        return _unauthorized()

    raw_path = str(request.query.get("path", "") or "").strip()
    image_path = _resolve_chat_image_path(raw_path)
    if image_path is None:
        return web.json_response({"error": "Invalid image path"}, status=400)

    return web.FileResponse(path=image_path)
