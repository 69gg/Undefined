from __future__ import annotations

from json import JSONDecodeError
from urllib.parse import quote

from aiohttp import ContentTypeError
from aiohttp import ClientSession, ClientTimeout, web
from aiohttp.web_response import Response, StreamResponse

from Undefined.config import get_config

from ._runtime import _proxy_runtime
from ._shared import check_auth, routes


def _unauthorized() -> Response:
    return web.json_response({"error": "Unauthorized"}, status=401)


async def _proxy_binary(request: web.Request, path: str) -> StreamResponse:
    cfg = get_config(strict=False)
    if not cfg.api.enabled:
        return web.json_response({"error": "Runtime API disabled"}, status=503)
    timeout = ClientTimeout(total=20.0)
    headers = {"X-Undefined-API-Key": str(cfg.api.auth_key or "")}
    url = f"{cfg.api.loopback_url}{path}"
    async with ClientSession(timeout=timeout) as session:
        async with session.get(url, headers=headers) as resp:
            response = web.StreamResponse(status=resp.status, reason=resp.reason)
            response.content_type = resp.content_type
            if resp.charset:
                response.charset = resp.charset
            for header_name in (
                "Content-Length",
                "Content-Disposition",
                "Cache-Control",
                "ETag",
                "Last-Modified",
            ):
                header_value = resp.headers.get(header_name)
                if header_value:
                    response.headers[header_name] = header_value
            await response.prepare(request)
            async for chunk in resp.content.iter_chunked(64 * 1024):
                await response.write(chunk)
            await response.write_eof()
            return response


@routes.get("/api/v1/management/memes")
async def management_memes_list_handler(request: web.Request) -> Response:
    if not check_auth(request):
        return _unauthorized()
    return await _proxy_runtime(
        method="GET",
        path="/api/v1/memes",
        params=request.query,
        timeout_seconds=30.0,
    )


@routes.get("/api/v1/management/memes/stats")
async def management_memes_stats_handler(request: web.Request) -> Response:
    if not check_auth(request):
        return _unauthorized()
    return await _proxy_runtime(
        method="GET",
        path="/api/v1/memes/stats",
        timeout_seconds=20.0,
    )


@routes.get("/api/v1/management/memes/{uid}")
async def management_meme_detail_handler(request: web.Request) -> Response:
    if not check_auth(request):
        return _unauthorized()
    uid = quote(str(request.match_info.get("uid", "")).strip(), safe="")
    return await _proxy_runtime(
        method="GET",
        path=f"/api/v1/memes/{uid}",
        timeout_seconds=20.0,
    )


@routes.get("/api/v1/management/memes/{uid}/blob")
async def management_meme_blob_handler(request: web.Request) -> StreamResponse:
    if not check_auth(request):
        return _unauthorized()
    uid = quote(str(request.match_info.get("uid", "")).strip(), safe="")
    return await _proxy_binary(request, f"/api/v1/memes/{uid}/blob")


@routes.get("/api/v1/management/memes/{uid}/preview")
async def management_meme_preview_handler(request: web.Request) -> StreamResponse:
    if not check_auth(request):
        return _unauthorized()
    uid = quote(str(request.match_info.get("uid", "")).strip(), safe="")
    return await _proxy_binary(request, f"/api/v1/memes/{uid}/preview")


@routes.patch("/api/v1/management/memes/{uid}")
async def management_meme_update_handler(request: web.Request) -> Response:
    if not check_auth(request):
        return _unauthorized()
    uid = quote(str(request.match_info.get("uid", "")).strip(), safe="")
    try:
        payload = await request.json()
    except (ContentTypeError, JSONDecodeError, UnicodeDecodeError, ValueError):
        return web.json_response({"error": "Invalid JSON payload"}, status=400)
    return await _proxy_runtime(
        method="PATCH",
        path=f"/api/v1/memes/{uid}",
        payload=payload,
        timeout_seconds=30.0,
    )


@routes.delete("/api/v1/management/memes/{uid}")
async def management_meme_delete_handler(request: web.Request) -> Response:
    if not check_auth(request):
        return _unauthorized()
    uid = quote(str(request.match_info.get("uid", "")).strip(), safe="")
    return await _proxy_runtime(
        method="DELETE",
        path=f"/api/v1/memes/{uid}",
        timeout_seconds=30.0,
    )


@routes.post("/api/v1/management/memes/{uid}/reanalyze")
async def management_meme_reanalyze_handler(request: web.Request) -> Response:
    if not check_auth(request):
        return _unauthorized()
    uid = quote(str(request.match_info.get("uid", "")).strip(), safe="")
    return await _proxy_runtime(
        method="POST",
        path=f"/api/v1/memes/{uid}/reanalyze",
        payload={},
        timeout_seconds=30.0,
    )


@routes.post("/api/v1/management/memes/{uid}/reindex")
async def management_meme_reindex_handler(request: web.Request) -> Response:
    if not check_auth(request):
        return _unauthorized()
    uid = quote(str(request.match_info.get("uid", "")).strip(), safe="")
    return await _proxy_runtime(
        method="POST",
        path=f"/api/v1/memes/{uid}/reindex",
        payload={},
        timeout_seconds=30.0,
    )
