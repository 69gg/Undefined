from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast
from urllib.parse import quote as _url_quote

from aiohttp import ClientSession, ClientTimeout, web
from aiohttp.web_response import Response

from Undefined.ai.queue_budget import compute_queued_llm_timeout_seconds
from Undefined.config import get_config
from Undefined.utils import io as async_io
from Undefined.utils.paths import CACHE_DIR, WEBUI_FILE_CACHE_DIR
from ._shared import check_auth, routes

_AUTH_HEADER = "X-Undefined-API-Key"
_MAX_CHAT_IMAGE_SIZE = 12 * 1024 * 1024
_ALLOWED_CHAT_IMAGE_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".bmp",
}
_WEBUI_FILE_UPLOAD_NAME_MAX_LENGTH = 128


def _runtime_base_url() -> str:
    return get_config(strict=False).api.loopback_url


def _chat_proxy_timeout_seconds() -> float:
    cfg = get_config(strict=False)
    return compute_queued_llm_timeout_seconds(cfg, cfg.chat_model)


def _load_function_name(config_path: Path) -> str | None:
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    function = raw.get("function", {})
    if not isinstance(function, dict):
        return None
    name = str(function.get("name", "") or "").strip()
    return name or None


def _load_top_level_agent_names(root: Path) -> set[str]:
    names: set[str] = set()
    if not root.exists():
        return names
    for item_dir in root.iterdir():
        if not item_dir.is_dir() or item_dir.name.startswith("_"):
            continue
        config_path = item_dir / "config.json"
        if not config_path.exists():
            continue
        name = _load_function_name(config_path)
        if name:
            names.add(name)
    return names


def _get_local_agent_tool_names() -> set[str]:
    from Undefined.utils.paths import PACKAGE_ROOT

    return _load_top_level_agent_names(PACKAGE_ROOT / "skills" / "agents")


def _tool_invoke_proxy_timeout_seconds(tool_name: str) -> float | None:
    normalized_name = str(tool_name or "").strip()
    if normalized_name in _get_local_agent_tool_names():
        return None

    cfg = get_config(strict=False)
    # 非 agent 一律保留 Runtime API 超时 + 60s 网络缓冲，
    # 包括 toolsets、MCP/external tools 以及本地未知名称。
    return float(cfg.api.tool_invoke_timeout) + 60.0


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


def _sanitize_upload_display_name(raw_name: str) -> str:
    name = Path(str(raw_name or "").strip() or "attachment").name or "attachment"
    if len(name) > _WEBUI_FILE_UPLOAD_NAME_MAX_LENGTH:
        suffix = "".join(Path(name).suffixes[-2:]) or Path(name).suffix
        suffix = suffix if len(suffix) <= 16 else ""
        name = f"attachment{suffix}"
    return name


def _random_upload_filename(display_name: str) -> str:
    suffix = "".join(Path(display_name).suffixes[-2:]) or Path(display_name).suffix
    suffix = suffix if len(suffix) <= 16 else ""
    return f"file_{uuid.uuid4().hex[:16]}{suffix}"


async def _proxy_runtime(
    *,
    method: str,
    path: str,
    params: Mapping[str, str] | None = None,
    payload: dict[str, Any] | None = None,
    timeout_seconds: float | None = 20.0,
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
    params: Mapping[str, str] | None = None,
    timeout_seconds: float | None = None,
) -> web.StreamResponse:
    cfg = get_config(strict=False)
    if not cfg.api.enabled:
        return _runtime_disabled()

    url = f"{_runtime_base_url()}{path}"
    if timeout_seconds is None:
        timeout_seconds = _chat_proxy_timeout_seconds()
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
                params=params,
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


@routes.get("/api/v1/management/runtime/meta")
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


@routes.get("/api/v1/management/runtime/openapi")
@routes.get("/api/runtime/openapi")
async def runtime_openapi_handler(request: web.Request) -> Response:
    if not check_auth(request):
        return _unauthorized()
    return await _proxy_runtime(
        method="GET",
        path="/openapi.json",
    )


@routes.get("/api/v1/management/runtime/probes/internal")
@routes.get("/api/runtime/probes/internal")
async def runtime_probe_internal_handler(request: web.Request) -> Response:
    if not check_auth(request):
        return _unauthorized()
    return await _proxy_runtime(method="GET", path="/api/v1/probes/internal")


@routes.get("/api/v1/management/runtime/probes/external")
@routes.get("/api/runtime/probes/external")
async def runtime_probe_external_handler(request: web.Request) -> Response:
    if not check_auth(request):
        return _unauthorized()
    return await _proxy_runtime(method="GET", path="/api/v1/probes/external")


@routes.get("/api/v1/management/runtime/memory")
@routes.get("/api/runtime/memory")
async def runtime_memory_handler(request: web.Request) -> Response:
    if not check_auth(request):
        return _unauthorized()
    return await _proxy_runtime(
        method="GET",
        path="/api/v1/memory",
        params=request.query,
    )


@routes.post("/api/v1/management/runtime/memory")
@routes.post("/api/runtime/memory")
async def runtime_memory_create_handler(request: web.Request) -> Response:
    if not check_auth(request):
        return _unauthorized()
    try:
        payload = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
        return web.json_response({"error": "Invalid JSON payload"}, status=400)
    return await _proxy_runtime(
        method="POST",
        path="/api/v1/memory",
        payload=payload,
    )


@routes.patch("/api/v1/management/runtime/memory/{uuid}")
@routes.patch("/api/runtime/memory/{uuid}")
async def runtime_memory_update_handler(request: web.Request) -> Response:
    if not check_auth(request):
        return _unauthorized()
    target_uuid = _url_quote(str(request.match_info.get("uuid", "")).strip(), safe="")
    try:
        payload = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
        return web.json_response({"error": "Invalid JSON payload"}, status=400)
    return await _proxy_runtime(
        method="PATCH",
        path=f"/api/v1/memory/{target_uuid}",
        payload=payload,
    )


@routes.delete("/api/v1/management/runtime/memory/{uuid}")
@routes.delete("/api/runtime/memory/{uuid}")
async def runtime_memory_delete_handler(request: web.Request) -> Response:
    if not check_auth(request):
        return _unauthorized()
    target_uuid = _url_quote(str(request.match_info.get("uuid", "")).strip(), safe="")
    return await _proxy_runtime(
        method="DELETE",
        path=f"/api/v1/memory/{target_uuid}",
    )


@routes.get("/api/v1/management/runtime/cognitive/events")
@routes.get("/api/runtime/cognitive/events")
async def runtime_cognitive_events_handler(request: web.Request) -> Response:
    if not check_auth(request):
        return _unauthorized()
    return await _proxy_runtime(
        method="GET",
        path="/api/v1/cognitive/events",
        params=request.query,
    )


@routes.get("/api/v1/management/runtime/cognitive/profiles")
@routes.get("/api/runtime/cognitive/profiles")
async def runtime_cognitive_profiles_handler(request: web.Request) -> Response:
    if not check_auth(request):
        return _unauthorized()
    return await _proxy_runtime(
        method="GET",
        path="/api/v1/cognitive/profiles",
        params=request.query,
    )


@routes.get("/api/v1/management/runtime/cognitive/profile/{entity_type}/{entity_id}")
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


@routes.get("/api/v1/management/runtime/commands")
@routes.get("/api/runtime/commands")
async def runtime_commands_list_handler(request: web.Request) -> Response:
    if not check_auth(request):
        return _unauthorized()
    return await _proxy_runtime(
        method="GET",
        path="/api/v1/commands",
        params=request.query,
    )


@routes.get("/api/v1/management/runtime/commands/{command_name}")
@routes.get("/api/runtime/commands/{command_name}")
async def runtime_command_detail_handler(request: web.Request) -> Response:
    if not check_auth(request):
        return _unauthorized()
    command_name = _url_quote(
        str(request.match_info.get("command_name", "")).strip(), safe=""
    )
    return await _proxy_runtime(
        method="GET",
        path=f"/api/v1/commands/{command_name}",
        params=request.query,
    )


@routes.post("/api/v1/management/runtime/chat")
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
    conversation_id = str(body.get("conversation_id", "") or "").strip()

    stream = _to_bool(body.get("stream"))
    payload: dict[str, Any] = {"message": message}
    if conversation_id:
        payload["conversation_id"] = conversation_id
    if stream:
        payload["stream"] = True
        return await _proxy_runtime_stream(
            request,
            method="POST",
            path="/api/v1/chat",
            payload=payload,
            timeout_seconds=_chat_proxy_timeout_seconds(),
        )

    return await _proxy_runtime(
        method="POST",
        path="/api/v1/chat",
        payload=payload,
        timeout_seconds=_chat_proxy_timeout_seconds(),
    )


@routes.get("/api/v1/management/runtime/chat/conversations")
@routes.get("/api/runtime/chat/conversations")
async def runtime_chat_conversations_handler(request: web.Request) -> Response:
    if not check_auth(request):
        return _unauthorized()
    return await _proxy_runtime(
        method="GET",
        path="/api/v1/chat/conversations",
        params=request.query,
    )


@routes.post("/api/v1/management/runtime/chat/conversations")
@routes.post("/api/runtime/chat/conversations")
async def runtime_chat_conversation_create_handler(request: web.Request) -> Response:
    if not check_auth(request):
        return _unauthorized()
    try:
        body = await request.json()
    except Exception:
        body = {}
    payload: dict[str, Any] = {}
    title = str(body.get("title", "") or "").strip()
    if title:
        payload["title"] = title
    return await _proxy_runtime(
        method="POST",
        path="/api/v1/chat/conversations",
        payload=payload,
    )


@routes.patch("/api/v1/management/runtime/chat/conversations/{conversation_id}")
@routes.patch("/api/runtime/chat/conversations/{conversation_id}")
async def runtime_chat_conversation_update_handler(request: web.Request) -> Response:
    if not check_auth(request):
        return _unauthorized()
    conversation_id = _url_quote(
        str(request.match_info.get("conversation_id", "")).strip(), safe=""
    )
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)
    return await _proxy_runtime(
        method="PATCH",
        path=f"/api/v1/chat/conversations/{conversation_id}",
        payload={"title": str(body.get("title", "") or "").strip()},
    )


@routes.delete("/api/v1/management/runtime/chat/conversations/{conversation_id}")
@routes.delete("/api/runtime/chat/conversations/{conversation_id}")
async def runtime_chat_conversation_delete_handler(request: web.Request) -> Response:
    if not check_auth(request):
        return _unauthorized()
    conversation_id = _url_quote(
        str(request.match_info.get("conversation_id", "")).strip(), safe=""
    )
    return await _proxy_runtime(
        method="DELETE",
        path=f"/api/v1/chat/conversations/{conversation_id}",
    )


@routes.get("/api/v1/management/runtime/chat/history")
@routes.get("/api/runtime/chat/history")
async def runtime_chat_history_handler(request: web.Request) -> Response:
    if not check_auth(request):
        return _unauthorized()
    return await _proxy_runtime(
        method="GET",
        path="/api/v1/chat/history",
        params=request.query,
    )


@routes.delete("/api/v1/management/runtime/chat/history")
@routes.delete("/api/runtime/chat/history")
async def runtime_chat_history_clear_handler(request: web.Request) -> Response:
    if not check_auth(request):
        return _unauthorized()
    return await _proxy_runtime(
        method="DELETE",
        path="/api/v1/chat/history",
        params=request.query,
    )


@routes.post("/api/v1/management/runtime/chat/jobs")
@routes.post("/api/runtime/chat/jobs")
async def runtime_chat_job_create_handler(request: web.Request) -> Response:
    if not check_auth(request):
        return _unauthorized()
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)
    message = str(body.get("message", "") or "").strip()
    if not message:
        return web.json_response({"error": "message is required"}, status=400)
    payload: dict[str, Any] = {"message": message}
    conversation_id = str(body.get("conversation_id", "") or "").strip()
    if conversation_id:
        payload["conversation_id"] = conversation_id
    return await _proxy_runtime(
        method="POST",
        path="/api/v1/chat/jobs",
        payload=payload,
        timeout_seconds=20.0,
    )


@routes.get("/api/v1/management/runtime/chat/jobs/active")
@routes.get("/api/runtime/chat/jobs/active")
async def runtime_chat_job_active_handler(request: web.Request) -> Response:
    if not check_auth(request):
        return _unauthorized()
    return await _proxy_runtime(
        method="GET",
        path="/api/v1/chat/jobs/active",
        params=request.query,
    )


@routes.get("/api/v1/management/runtime/chat/jobs/{job_id}")
@routes.get("/api/runtime/chat/jobs/{job_id}")
async def runtime_chat_job_detail_handler(request: web.Request) -> Response:
    if not check_auth(request):
        return _unauthorized()
    job_id = _url_quote(str(request.match_info.get("job_id", "")).strip(), safe="")
    return await _proxy_runtime(method="GET", path=f"/api/v1/chat/jobs/{job_id}")


@routes.get("/api/v1/management/runtime/chat/jobs/{job_id}/events")
@routes.get("/api/runtime/chat/jobs/{job_id}/events")
async def runtime_chat_job_events_handler(request: web.Request) -> web.StreamResponse:
    if not check_auth(request):
        return _unauthorized()
    job_id = _url_quote(str(request.match_info.get("job_id", "")).strip(), safe="")
    wants_json = (
        str(request.query.get("format", "") or "").strip().lower() == "json"
        or "application/json"
        in str(request.headers.get("Accept", "") or "").strip().lower()
    )
    if wants_json:
        return await _proxy_runtime(
            method="GET",
            path=f"/api/v1/chat/jobs/{job_id}/events",
            params=request.query,
            timeout_seconds=20.0,
        )
    return await _proxy_runtime_stream(
        request,
        method="GET",
        path=f"/api/v1/chat/jobs/{job_id}/events",
        params=request.query,
        timeout_seconds=_chat_proxy_timeout_seconds(),
    )


@routes.post("/api/v1/management/runtime/chat/jobs/{job_id}/cancel")
@routes.post("/api/runtime/chat/jobs/{job_id}/cancel")
async def runtime_chat_job_cancel_handler(request: web.Request) -> Response:
    if not check_auth(request):
        return _unauthorized()
    job_id = _url_quote(str(request.match_info.get("job_id", "")).strip(), safe="")
    return await _proxy_runtime(
        method="POST",
        path=f"/api/v1/chat/jobs/{job_id}/cancel",
        timeout_seconds=20.0,
    )


@routes.get("/api/v1/management/runtime/chat/image")
@routes.get("/api/runtime/chat/image")
async def runtime_chat_image_handler(request: web.Request) -> web.StreamResponse:
    if not check_auth(request):
        return _unauthorized()

    raw_path = str(request.query.get("path", "") or "").strip()
    image_path = _resolve_chat_image_path(raw_path)
    if image_path is None:
        return web.json_response({"error": "Invalid image path"}, status=400)

    return web.FileResponse(path=image_path)


@routes.get("/api/v1/management/runtime/chat/file")
@routes.get("/api/runtime/chat/file")
async def runtime_chat_file_handler(request: web.Request) -> web.StreamResponse:
    """提供 WebUI 虚拟私聊文件下载。"""
    if not check_auth(request):
        return _unauthorized()

    file_id = str(request.query.get("id", "") or "").strip()
    if not file_id or not file_id.isalnum():
        return web.json_response({"error": "Invalid file id"}, status=400)

    file_dir = (Path.cwd() / WEBUI_FILE_CACHE_DIR / file_id).resolve()
    cache_root = (Path.cwd() / WEBUI_FILE_CACHE_DIR).resolve()
    if cache_root not in file_dir.parents and file_dir != cache_root:
        return web.json_response({"error": "Invalid file id"}, status=400)
    if not file_dir.is_dir():
        return web.json_response({"error": "File not found"}, status=404)

    try:
        files = list(file_dir.iterdir())
    except OSError:
        return web.json_response({"error": "File not found"}, status=404)
    if not files:
        return web.json_response({"error": "File not found"}, status=404)

    target = files[0]
    if not target.is_file():
        return web.json_response({"error": "File not found"}, status=404)

    # RFC 5987 编码：ASCII fallback + UTF-8 filename*
    raw_name = target.name
    ascii_name = raw_name.encode("ascii", errors="replace").decode("ascii")
    utf8_name = _url_quote(raw_name, safe="")
    disposition = f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{utf8_name}"

    return web.FileResponse(
        path=target,
        headers={"Content-Disposition": disposition},
    )


@routes.post("/api/v1/management/runtime/chat/files")
@routes.post("/api/runtime/chat/files")
async def runtime_chat_file_upload_handler(request: web.Request) -> Response:
    """缓存 WebChat 待发送附件，发送时通过 CQ:file id 引用。"""
    if not check_auth(request):
        return _unauthorized()

    try:
        reader = await request.multipart()
        field = await reader.next()
    except Exception:
        return web.json_response({"error": "Invalid multipart body"}, status=400)

    field_any = cast(Any, field)
    if field is None or getattr(field_any, "name", None) != "file":
        return web.json_response({"error": "file field is required"}, status=400)

    raw_name = _sanitize_upload_display_name(
        str(getattr(field_any, "filename", "") or "attachment")
    )
    file_id = uuid.uuid4().hex
    dest_dir = (Path.cwd() / WEBUI_FILE_CACHE_DIR / file_id).resolve()
    cache_root = (Path.cwd() / WEBUI_FILE_CACHE_DIR).resolve()
    if cache_root not in dest_dir.parents and dest_dir != cache_root:
        return web.json_response({"error": "Invalid file path"}, status=400)
    dest = dest_dir / _random_upload_filename(raw_name)
    cfg = get_config(strict=False)
    max_size_mb = max(1, int(getattr(cfg, "messages_send_url_file_max_size_mb", 100)))
    max_size_bytes = max_size_mb * 1024 * 1024

    size = 0
    chunks = bytearray()
    try:
        while True:
            chunk = await field_any.read_chunk()
            if not chunk:
                break
            size += len(chunk)
            if size > max_size_bytes:
                await async_io.delete_tree(dest_dir)
                return web.json_response(
                    {"error": "file too large", "max_size": max_size_bytes},
                    status=413,
                )
            chunks.extend(chunk)
        await async_io.write_bytes(dest, bytes(chunks), use_lock=False)
    except Exception:
        await async_io.delete_tree(dest_dir)
        raise

    return web.json_response(
        {
            "id": file_id,
            "name": raw_name,
            "size": size,
        }
    )


# ------------------------------------------------------------------
# Tool Invoke API proxy
# ------------------------------------------------------------------


@routes.get("/api/v1/management/runtime/tools")
@routes.get("/api/runtime/tools")
async def runtime_tools_list_handler(request: web.Request) -> Response:
    if not check_auth(request):
        return _unauthorized()
    return await _proxy_runtime(
        method="GET",
        path="/api/v1/tools",
    )


@routes.post("/api/v1/management/runtime/tools/invoke")
@routes.post("/api/runtime/tools/invoke")
async def runtime_tools_invoke_handler(request: web.Request) -> Response:
    if not check_auth(request):
        return _unauthorized()
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    tool_name = str(body.get("tool_name", "") or "").strip()
    proxy_timeout = _tool_invoke_proxy_timeout_seconds(tool_name)
    return await _proxy_runtime(
        method="POST",
        path="/api/v1/tools/invoke",
        payload=body,
        timeout_seconds=proxy_timeout,
    )
