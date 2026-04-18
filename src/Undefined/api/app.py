from __future__ import annotations

import asyncio
from copy import deepcopy
import hashlib
import json
import logging
import os
import platform
from pathlib import Path
import socket
import sys
import time
import uuid as _uuid
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Awaitable, Callable
from typing import cast
from urllib.parse import urlsplit
from aiohttp import ClientSession, ClientTimeout, web
from aiohttp.web_response import Response

from Undefined import __version__
from Undefined.attachments import (
    attachment_refs_to_xml,
    build_attachment_scope,
    register_message_attachments,
    render_message_with_pic_placeholders,
)
from Undefined.config import load_webui_settings
from Undefined.context import RequestContext
from Undefined.context_resource_registry import collect_context_resources
from Undefined.render import render_html_to_image, render_markdown_to_html  # noqa: F401
from Undefined.services.queue_manager import QUEUE_LANE_SUPERADMIN
from Undefined.utils.common import message_to_segments
from Undefined.utils.cors import is_allowed_cors_origin, normalize_origin
from Undefined.utils.recent_messages import get_recent_messages_prefer_local
from Undefined.utils.xml import escape_xml_attr, escape_xml_text

logger = logging.getLogger(__name__)

_VIRTUAL_USER_ID = 42
_VIRTUAL_USER_NAME = "system"
_AUTH_HEADER = "X-Undefined-API-Key"
_CHAT_SSE_KEEPALIVE_SECONDS = 10.0
_PROCESS_START_TIME = time.time()
_NAGA_REQUEST_UUID_TTL_SECONDS = 6 * 60 * 60


class _ToolInvokeExecutionTimeoutError(asyncio.TimeoutError):
    """由 Runtime API 工具调用超时包装器抛出的超时异常。"""


@dataclass
class _NagaRequestResult:
    payload_hash: str
    status: int
    payload: dict[str, Any]
    finished_at: float


class _WebUIVirtualSender:
    """将工具发送行为重定向到 WebUI 会话，不触发 OneBot 实际发送。"""

    def __init__(
        self,
        virtual_user_id: int,
        send_private_callback: Callable[[int, str], Awaitable[None]],
        onebot: Any = None,
    ) -> None:
        self._virtual_user_id = virtual_user_id
        self._send_private_callback = send_private_callback
        # 保留 onebot 属性，兼容依赖 sender.onebot 的工具读取能力。
        self.onebot = onebot

    async def send_private_message(
        self,
        user_id: int,
        message: str,
        auto_history: bool = True,
        *,
        mark_sent: bool = True,
        reply_to: int | None = None,
        preferred_temp_group_id: int | None = None,
        history_message: str | None = None,
    ) -> int | None:
        _ = (
            user_id,
            auto_history,
            mark_sent,
            reply_to,
            preferred_temp_group_id,
            history_message,
        )
        await self._send_private_callback(self._virtual_user_id, message)
        return None

    async def send_group_message(
        self,
        group_id: int,
        message: str,
        auto_history: bool = True,
        history_prefix: str = "",
        *,
        mark_sent: bool = True,
        reply_to: int | None = None,
        history_message: str | None = None,
    ) -> int | None:
        _ = (
            group_id,
            auto_history,
            history_prefix,
            mark_sent,
            reply_to,
            history_message,
        )
        await self._send_private_callback(self._virtual_user_id, message)
        return None

    async def send_private_file(
        self,
        user_id: int,
        file_path: str,
        name: str | None = None,
        auto_history: bool = True,
    ) -> None:
        """将文件拷贝到 WebUI 缓存并发送文件卡片消息。"""
        _ = user_id, auto_history
        import shutil
        import uuid as _uuid
        from pathlib import Path as _Path

        from Undefined.utils.paths import WEBUI_FILE_CACHE_DIR, ensure_dir

        src = _Path(file_path)
        display_name = name or src.name
        file_id = _uuid.uuid4().hex
        dest_dir = ensure_dir(WEBUI_FILE_CACHE_DIR / file_id)
        dest = dest_dir / display_name

        def _copy_and_stat() -> int:
            shutil.copy2(src, dest)
            return dest.stat().st_size

        try:
            file_size = await asyncio.to_thread(_copy_and_stat)
        except OSError:
            file_size = 0

        message = f"[CQ:file,id={file_id},name={display_name},size={file_size}]"
        await self._send_private_callback(self._virtual_user_id, message)

    async def send_group_file(
        self,
        group_id: int,
        file_path: str,
        name: str | None = None,
        auto_history: bool = True,
    ) -> None:
        """群文件在虚拟会话中同样重定向为文本消息。"""
        await self.send_private_file(group_id, file_path, name, auto_history)


@dataclass
class RuntimeAPIContext:
    config_getter: Callable[[], Any]
    onebot: Any
    ai: Any
    command_dispatcher: Any
    queue_manager: Any
    history_manager: Any
    sender: Any = None
    scheduler: Any = None
    cognitive_service: Any = None
    cognitive_job_queue: Any = None
    meme_service: Any = None
    naga_store: Any = None


def _json_error(message: str, status: int = 400) -> Response:
    return web.json_response({"error": message}, status=status)


def _apply_cors_headers(request: web.Request, response: web.StreamResponse) -> None:
    origin = normalize_origin(str(request.headers.get("Origin") or ""))
    settings = load_webui_settings()
    response.headers.setdefault("Vary", "Origin")
    response.headers.setdefault("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
    response.headers.setdefault(
        "Access-Control-Allow-Headers",
        "Authorization, Content-Type, X-Undefined-API-Key",
    )
    response.headers.setdefault("Access-Control-Max-Age", "86400")
    if origin and is_allowed_cors_origin(
        origin,
        configured_host=str(settings.url or ""),
        configured_port=settings.port,
    ):
        response.headers.setdefault("Access-Control-Allow-Origin", origin)
        response.headers.setdefault("Access-Control-Allow-Credentials", "true")


def _optional_query_param(request: web.Request, key: str) -> str | None:
    raw = request.query.get(key)
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    return text


def _parse_query_time(value: str | None) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    candidates = [text, text.replace("Z", "+00:00")]
    if "T" in text:
        candidates.append(text.replace("T", " "))
    for candidate in candidates:
        with suppress(ValueError):
            return datetime.fromisoformat(candidate)
    return None


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    text = str(value or "").strip().lower()
    return text in {"1", "true", "yes", "on"}


def _build_chat_response_payload(mode: str, outputs: list[str]) -> dict[str, Any]:
    return {
        "mode": mode,
        "virtual_user_id": _VIRTUAL_USER_ID,
        "permission": "superadmin",
        "messages": outputs,
        "reply": "\n\n".join(outputs).strip(),
    }


def _sse_event(event: str, payload: dict[str, Any]) -> bytes:
    data = json.dumps(payload, ensure_ascii=False)
    return f"event: {event}\ndata: {data}\n\n".encode("utf-8")


def _mask_url(url: str) -> str:
    """保留 scheme + host，隐藏 path 细节。"""
    text = str(url or "").strip().rstrip("/")
    if not text:
        return ""
    parsed = urlsplit(text)
    host = parsed.hostname or ""
    port_part = f":{parsed.port}" if parsed.port else ""
    scheme = parsed.scheme or "https"
    return f"{scheme}://{host}{port_part}/..."


def _naga_runtime_enabled(cfg: Any) -> bool:
    naga_cfg = getattr(cfg, "naga", None)
    return bool(getattr(cfg, "nagaagent_mode_enabled", False)) and bool(
        getattr(naga_cfg, "enabled", False)
    )


def _naga_routes_enabled(cfg: Any, naga_store: Any) -> bool:
    return _naga_runtime_enabled(cfg) and naga_store is not None


def _short_text_preview(text: str, limit: int = 80) -> str:
    compact = " ".join(str(text or "").split())
    if len(compact) <= limit:
        return compact
    return compact[:limit] + "..."


def _naga_message_digest(
    *,
    bind_uuid: str,
    naga_id: str,
    target_qq: int,
    target_group: int,
    mode: str,
    message_format: str,
    content: str,
) -> str:
    raw = json.dumps(
        {
            "bind_uuid": bind_uuid,
            "naga_id": naga_id,
            "target_qq": target_qq,
            "target_group": target_group,
            "mode": mode,
            "format": message_format,
            "content": content,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _parse_response_payload(response: Response) -> dict[str, Any]:
    text = response.text or ""
    if not text:
        return {}
    payload = json.loads(text)
    return payload if isinstance(payload, dict) else {"data": payload}


def _registry_summary(registry: Any) -> dict[str, Any]:
    """从 BaseRegistry 提取轻量摘要。"""
    if registry is None:
        return {"count": 0, "loaded": 0, "items": []}
    items: dict[str, Any] = getattr(registry, "_items", {})
    stats: dict[str, Any] = {}
    get_stats = getattr(registry, "get_stats", None)
    if callable(get_stats):
        stats = get_stats()
    summary_items: list[dict[str, Any]] = []
    for name, item in items.items():
        st = stats.get(name)
        entry: dict[str, Any] = {
            "name": name,
            "loaded": getattr(item, "loaded", False),
        }
        if st is not None:
            entry["calls"] = getattr(st, "count", 0)
            entry["success"] = getattr(st, "success", 0)
            entry["failure"] = getattr(st, "failure", 0)
        summary_items.append(entry)
    return {
        "count": len(items),
        "loaded": sum(1 for i in items.values() if getattr(i, "loaded", False)),
        "items": summary_items,
    }


def _validate_callback_url(url: str) -> str | None:
    """校验回调 URL，返回错误信息或 None 表示通过。

    拒绝非 HTTP(S) scheme，以及直接使用私有/回环 IP 字面量的 URL 以防止 SSRF。
    域名形式的 URL 放行（DNS 解析阶段不适合在校验函数中做阻塞调用）。
    """
    import ipaddress

    parsed = urlsplit(url)
    scheme = (parsed.scheme or "").lower()

    if scheme not in ("http", "https"):
        return "callback.url must use http or https"

    hostname = parsed.hostname or ""
    if not hostname:
        return "callback.url must include a hostname"

    # 仅检查 IP 字面量（如 http://127.0.0.1/、http://[::1]/、http://10.0.0.1/）
    try:
        addr = ipaddress.ip_address(hostname)
    except ValueError:
        pass  # 域名形式，放行
    else:
        if addr.is_private or addr.is_loopback or addr.is_link_local:
            return "callback.url must not point to a private/loopback address"

    return None


async def _probe_http_endpoint(
    *,
    name: str,
    base_url: str,
    api_key: str,
    model_name: str = "",
    timeout_seconds: float = 5.0,
) -> dict[str, Any]:
    normalized = str(base_url or "").strip().rstrip("/")
    if not normalized:
        return {
            "name": name,
            "status": "skipped",
            "reason": "empty_url",
            "model_name": model_name,
        }

    headers: dict[str, str] = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    candidates = [normalized, f"{normalized}/models"]
    last_error = ""
    for url in candidates:
        start = time.perf_counter()
        try:
            timeout = ClientTimeout(total=timeout_seconds)
            async with ClientSession(timeout=timeout) as session:
                async with session.get(url, headers=headers) as resp:
                    elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
                    return {
                        "name": name,
                        "status": "ok",
                        "url": _mask_url(url),
                        "http_status": resp.status,
                        "latency_ms": elapsed_ms,
                        "model_name": model_name,
                    }
        except Exception as exc:
            last_error = str(exc)
            continue

    return {
        "name": name,
        "status": "error",
        "url": _mask_url(normalized),
        "error": last_error or "request_failed",
        "model_name": model_name,
    }


async def _skipped_probe(
    *, name: str, reason: str, model_name: str = ""
) -> dict[str, Any]:
    payload: dict[str, Any] = {"name": name, "status": "skipped", "reason": reason}
    if model_name:
        payload["model_name"] = model_name
    return payload


def _build_internal_model_probe_payload(mcfg: Any) -> dict[str, Any]:
    payload = {
        "model_name": getattr(mcfg, "model_name", ""),
        "api_url": _mask_url(getattr(mcfg, "api_url", "")),
    }
    if hasattr(mcfg, "api_mode"):
        payload["api_mode"] = getattr(mcfg, "api_mode", "chat_completions")
    if hasattr(mcfg, "thinking_enabled"):
        payload["thinking_enabled"] = getattr(mcfg, "thinking_enabled", False)
    if hasattr(mcfg, "thinking_tool_call_compat"):
        payload["thinking_tool_call_compat"] = getattr(
            mcfg, "thinking_tool_call_compat", True
        )
    if hasattr(mcfg, "responses_tool_choice_compat"):
        payload["responses_tool_choice_compat"] = getattr(
            mcfg, "responses_tool_choice_compat", False
        )
    if hasattr(mcfg, "responses_force_stateless_replay"):
        payload["responses_force_stateless_replay"] = getattr(
            mcfg, "responses_force_stateless_replay", False
        )
    if hasattr(mcfg, "prompt_cache_enabled"):
        payload["prompt_cache_enabled"] = getattr(mcfg, "prompt_cache_enabled", True)
    if hasattr(mcfg, "reasoning_enabled"):
        payload["reasoning_enabled"] = getattr(mcfg, "reasoning_enabled", False)
    if hasattr(mcfg, "reasoning_effort"):
        payload["reasoning_effort"] = getattr(mcfg, "reasoning_effort", "medium")
    return payload


async def _probe_ws_endpoint(url: str, timeout_seconds: float = 5.0) -> dict[str, Any]:
    normalized = str(url or "").strip()
    if not normalized:
        return {"name": "onebot_ws", "status": "skipped", "reason": "empty_url"}

    parsed = urlsplit(normalized)
    host = parsed.hostname
    if not host:
        return {"name": "onebot_ws", "status": "error", "error": "invalid_url"}

    if parsed.port is not None:
        port = parsed.port
    elif parsed.scheme == "wss":
        port = 443
    else:
        port = 80

    start = time.perf_counter()
    try:
        conn = asyncio.open_connection(host, port)
        reader, writer = await asyncio.wait_for(conn, timeout=timeout_seconds)
        writer.close()
        await writer.wait_closed()
        elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
        return {
            "name": "onebot_ws",
            "status": "ok",
            "host": host,
            "port": port,
            "latency_ms": elapsed_ms,
        }
    except (OSError, TimeoutError, socket.gaierror, asyncio.TimeoutError) as exc:
        return {
            "name": "onebot_ws",
            "status": "error",
            "host": host,
            "port": port,
            "error": str(exc),
        }


def _build_openapi_spec(ctx: RuntimeAPIContext, request: web.Request) -> dict[str, Any]:
    server_url = f"{request.scheme}://{request.host}"
    cfg = ctx.config_getter()
    naga_routes_enabled = _naga_routes_enabled(cfg, ctx.naga_store)
    paths: dict[str, Any] = {
        "/health": {
            "get": {
                "summary": "Health check",
                "security": [],
                "responses": {"200": {"description": "OK"}},
            }
        },
        "/openapi.json": {
            "get": {
                "summary": "OpenAPI schema",
                "security": [],
                "responses": {"200": {"description": "Schema JSON"}},
            }
        },
        "/api/v1/probes/internal": {
            "get": {
                "summary": "Internal runtime probes",
                "description": (
                    "Returns system info (version, Python, platform, uptime), "
                    "OneBot connection status, request queue snapshot, "
                    "memory count, cognitive service status, API config, "
                    "skill statistics (tools/agents/anthropic_skills with call counts), "
                    "and model configuration (names, masked URLs, thinking flags)."
                ),
            }
        },
        "/api/v1/probes/external": {
            "get": {
                "summary": "External dependency probes",
                "description": (
                    "Concurrently probes all configured model API endpoints "
                    "(chat, vision, security, naga, agent, embedding, rerank) "
                    "and OneBot WebSocket. Each result includes status, "
                    "model name, masked URL, HTTP status code, and latency."
                ),
            }
        },
        "/api/v1/memory": {"get": {"summary": "List/search manual memories"}},
        "/api/v1/memes": {"get": {"summary": "List/search meme library items"}},
        "/api/v1/memes/stats": {"get": {"summary": "Get meme library stats"}},
        "/api/v1/memes/{uid}": {
            "get": {"summary": "Get a meme by uid"},
            "patch": {"summary": "Update a meme by uid"},
            "delete": {"summary": "Delete a meme by uid"},
        },
        "/api/v1/memes/{uid}/blob": {"get": {"summary": "Get meme blob file"}},
        "/api/v1/memes/{uid}/preview": {"get": {"summary": "Get meme preview file"}},
        "/api/v1/memes/{uid}/reanalyze": {
            "post": {"summary": "Queue a meme reanalyze job"}
        },
        "/api/v1/memes/{uid}/reindex": {
            "post": {"summary": "Queue a meme reindex job"}
        },
        "/api/v1/cognitive/events": {
            "get": {"summary": "Search cognitive event memories"}
        },
        "/api/v1/cognitive/profiles": {"get": {"summary": "Search cognitive profiles"}},
        "/api/v1/cognitive/profile/{entity_type}/{entity_id}": {
            "get": {"summary": "Get a profile by entity type/id"}
        },
        "/api/v1/chat": {
            "post": {
                "summary": "WebUI special private chat",
                "description": (
                    "POST JSON {message, stream?}. "
                    "When stream=true, response is SSE with keep-alive comments."
                ),
            }
        },
        "/api/v1/chat/history": {
            "get": {"summary": "Get virtual private chat history for WebUI"}
        },
        "/api/v1/tools": {
            "get": {
                "summary": "List available tools",
                "description": (
                    "Returns currently available tools filtered by "
                    "tool_invoke_expose / allowlist / denylist config. "
                    "Each item follows the OpenAI function calling schema."
                ),
            }
        },
        "/api/v1/tools/invoke": {
            "post": {
                "summary": "Invoke a tool",
                "description": (
                    "Execute a specific tool by name. Supports synchronous "
                    "response and optional async webhook callback."
                ),
            }
        },
    }

    if naga_routes_enabled:
        paths.update(
            {
                "/api/v1/naga/bind/callback": {
                    "post": {
                        "summary": "Finalize a Naga bind request",
                        "description": (
                            "Internal callback used by Naga to approve or reject "
                            "a bind_uuid."
                        ),
                        "security": [{"BearerAuth": []}],
                    }
                },
                "/api/v1/naga/messages/send": {
                    "post": {
                        "summary": "Send a Naga-authenticated message",
                        "description": (
                            "Validates bind_uuid + delivery_signature, runs "
                            "moderation, then delivers the message. "
                            "Caller may provide uuid for idempotent retry deduplication."
                        ),
                        "security": [{"BearerAuth": []}],
                    }
                },
                "/api/v1/naga/unbind": {
                    "post": {
                        "summary": "Revoke an active Naga binding",
                        "description": (
                            "Allows Naga to proactively revoke a binding using "
                            "Authorization: Bearer <naga.api_key>."
                        ),
                        "security": [{"BearerAuth": []}],
                    }
                },
            }
        )

    return {
        "openapi": "3.0.3",
        "info": {
            "title": "Undefined Runtime API",
            "version": __version__,
            "description": "API exposed by the main Undefined process.",
        },
        "servers": [
            {
                "url": server_url,
                "description": "Runtime endpoint",
            }
        ],
        "components": {
            "securitySchemes": {
                "ApiKeyAuth": {
                    "type": "apiKey",
                    "in": "header",
                    "name": _AUTH_HEADER,
                },
                "BearerAuth": {"type": "http", "scheme": "bearer"},
            }
        },
        "security": [{"ApiKeyAuth": []}],
        "paths": paths,
    }


class RuntimeAPIServer:
    def __init__(
        self,
        context: RuntimeAPIContext,
        host: str,
        port: int,
    ) -> None:
        self._context = context
        self._host = host
        self._port = port
        self._runner: web.AppRunner | None = None
        self._sites: list[web.TCPSite] = []
        self._background_tasks: set[asyncio.Task[Any]] = set()
        self._naga_send_registry_lock = asyncio.Lock()
        self._naga_send_inflight: dict[str, int] = {}
        self._naga_request_uuid_lock = asyncio.Lock()
        self._naga_request_uuid_inflight: dict[
            str, tuple[str, asyncio.Future[tuple[int, dict[str, Any]]]]
        ] = {}
        self._naga_request_uuid_results: dict[str, _NagaRequestResult] = {}

    async def start(self) -> None:
        from Undefined.config.models import resolve_bind_hosts

        app = self._create_app()
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        for h in resolve_bind_hosts(self._host):
            site = web.TCPSite(self._runner, host=h, port=self._port)
            await site.start()
            self._sites.append(site)
        cfg = self._context.config_getter()
        logger.info("[RuntimeAPI] 已启动: %s", cfg.api.display_url)

    async def stop(self) -> None:
        # 取消所有后台任务（如异步 tool invoke 回调）
        for task in self._background_tasks:
            task.cancel()
        if self._background_tasks:
            await asyncio.gather(*self._background_tasks, return_exceptions=True)
            self._background_tasks.clear()

        if self._runner is not None:
            await self._runner.cleanup()
            logger.info("[RuntimeAPI] 已停止")
        self._runner = None
        self._site = None

    def _create_app(self) -> web.Application:
        @web.middleware
        async def _auth_middleware(
            request: web.Request,
            handler: Callable[[web.Request], Awaitable[web.StreamResponse]],
        ) -> web.StreamResponse:
            response: web.StreamResponse
            if request.method == "OPTIONS":
                response = web.Response(status=204)
                _apply_cors_headers(request, response)
                return response
            if request.path.startswith("/api/"):
                # Naga 端点使用独立鉴权，仅在总开关+子开关均启用时跳过主 auth
                cfg = self._context.config_getter()
                is_naga_path = request.path.startswith("/api/v1/naga/")
                skip_auth = is_naga_path and _naga_runtime_enabled(cfg)
                if not skip_auth:
                    expected = str(cfg.api.auth_key or "")
                    provided = request.headers.get(_AUTH_HEADER, "")
                    if not expected or provided != expected:
                        response = _json_error("Unauthorized", status=401)
                        _apply_cors_headers(request, response)
                        return response
            response = await handler(request)
            _apply_cors_headers(request, response)
            return response

        app = web.Application(middlewares=[_auth_middleware])
        app["runtime_api_context"] = self._context
        app.add_routes(
            [
                web.get("/health", self._health_handler),
                web.get("/openapi.json", self._openapi_handler),
                web.get("/api/v1/probes/internal", self._internal_probe_handler),
                web.get("/api/v1/probes/external", self._external_probe_handler),
                web.get("/api/v1/memory", self._memory_handler),
                web.get("/api/v1/memes", self._meme_list_handler),
                web.get("/api/v1/memes/stats", self._meme_stats_handler),
                web.get("/api/v1/memes/{uid}", self._meme_detail_handler),
                web.get("/api/v1/memes/{uid}/blob", self._meme_blob_handler),
                web.get("/api/v1/memes/{uid}/preview", self._meme_preview_handler),
                web.patch("/api/v1/memes/{uid}", self._meme_update_handler),
                web.delete("/api/v1/memes/{uid}", self._meme_delete_handler),
                web.post(
                    "/api/v1/memes/{uid}/reanalyze",
                    self._meme_reanalyze_handler,
                ),
                web.post(
                    "/api/v1/memes/{uid}/reindex",
                    self._meme_reindex_handler,
                ),
                web.get("/api/v1/cognitive/events", self._cognitive_events_handler),
                web.get(
                    "/api/v1/cognitive/profiles",
                    self._cognitive_profiles_handler,
                ),
                web.get(
                    "/api/v1/cognitive/profile/{entity_type}/{entity_id}",
                    self._cognitive_profile_handler,
                ),
                web.post("/api/v1/chat", self._chat_handler),
                web.get("/api/v1/chat/history", self._chat_history_handler),
                web.get("/api/v1/tools", self._tools_list_handler),
                web.post("/api/v1/tools/invoke", self._tools_invoke_handler),
            ]
        )
        # Naga 端点仅在总开关+子开关均启用时注册
        cfg = self._context.config_getter()
        if _naga_routes_enabled(cfg, self._context.naga_store):
            app.add_routes(
                [
                    web.post(
                        "/api/v1/naga/bind/callback",
                        self._naga_bind_callback_handler,
                    ),
                    web.post(
                        "/api/v1/naga/messages/send",
                        self._naga_messages_send_handler,
                    ),
                    web.post("/api/v1/naga/unbind", self._naga_unbind_handler),
                ]
            )
            logger.info(
                "[RuntimeAPI] Naga 端点已注册: bind_callback=%s messages_send=%s unbind=%s",
                "/api/v1/naga/bind/callback",
                "/api/v1/naga/messages/send",
                "/api/v1/naga/unbind",
            )
        else:
            naga_cfg = getattr(cfg, "naga", None)
            logger.info(
                "[RuntimeAPI] Naga 端点未注册: mode_enabled=%s naga_enabled=%s store_ready=%s",
                bool(getattr(cfg, "nagaagent_mode_enabled", False)),
                bool(getattr(naga_cfg, "enabled", False)),
                self._context.naga_store is not None,
            )
        return app

    async def _track_naga_send_start(self, message_key: str) -> int:
        async with self._naga_send_registry_lock:
            next_count = self._naga_send_inflight.get(message_key, 0) + 1
            self._naga_send_inflight[message_key] = next_count
            return next_count

    async def _track_naga_send_done(self, message_key: str) -> int:
        async with self._naga_send_registry_lock:
            current = self._naga_send_inflight.get(message_key, 0)
            if current <= 1:
                self._naga_send_inflight.pop(message_key, None)
                return 0
            next_count = current - 1
            self._naga_send_inflight[message_key] = next_count
            return next_count

    def _prune_naga_request_uuid_state_locked(self) -> None:
        now = time.time()
        expired = [
            request_uuid
            for request_uuid, result in self._naga_request_uuid_results.items()
            if now - result.finished_at > _NAGA_REQUEST_UUID_TTL_SECONDS
        ]
        for request_uuid in expired:
            self._naga_request_uuid_results.pop(request_uuid, None)

    async def _register_naga_request_uuid(
        self, request_uuid: str, payload_hash: str
    ) -> tuple[str, Any]:
        async with self._naga_request_uuid_lock:
            self._prune_naga_request_uuid_state_locked()

            cached = self._naga_request_uuid_results.get(request_uuid)
            if cached is not None:
                if cached.payload_hash != payload_hash:
                    return "conflict", cached.payload_hash
                return "cached", (cached.status, deepcopy(cached.payload))

            inflight = self._naga_request_uuid_inflight.get(request_uuid)
            if inflight is not None:
                existing_hash, inflight_future = inflight
                if existing_hash != payload_hash:
                    return "conflict", existing_hash
                return "await", inflight_future

            owner_future: asyncio.Future[tuple[int, dict[str, Any]]] = (
                asyncio.get_running_loop().create_future()
            )
            self._naga_request_uuid_inflight[request_uuid] = (
                payload_hash,
                owner_future,
            )
            return "owner", owner_future

    async def _finish_naga_request_uuid(
        self,
        request_uuid: str,
        payload_hash: str,
        *,
        status: int,
        payload: dict[str, Any],
    ) -> None:
        async with self._naga_request_uuid_lock:
            inflight = self._naga_request_uuid_inflight.pop(request_uuid, None)
            future = inflight[1] if inflight is not None else None
            result_payload = deepcopy(payload)
            self._naga_request_uuid_results[request_uuid] = _NagaRequestResult(
                payload_hash=payload_hash,
                status=status,
                payload=result_payload,
                finished_at=time.time(),
            )
            self._prune_naga_request_uuid_state_locked()
            if future is not None and not future.done():
                future.set_result((status, deepcopy(result_payload)))

    async def _fail_naga_request_uuid(
        self,
        request_uuid: str,
        payload_hash: str,
        exc: BaseException,
    ) -> None:
        async with self._naga_request_uuid_lock:
            inflight = self._naga_request_uuid_inflight.pop(request_uuid, None)
            future = inflight[1] if inflight is not None else None
            self._prune_naga_request_uuid_state_locked()
            if future is not None and not future.done():
                future.set_exception(exc)

    @property
    def _ctx(self) -> RuntimeAPIContext:
        return self._context

    async def _health_handler(self, request: web.Request) -> Response:
        _ = request
        return web.json_response(
            {
                "ok": True,
                "service": "undefined-runtime-api",
                "version": __version__,
                "timestamp": datetime.now().isoformat(),
            }
        )

    async def _openapi_handler(self, request: web.Request) -> Response:
        cfg = self._ctx.config_getter()
        if not bool(getattr(cfg.api, "openapi_enabled", True)):
            logger.info(
                "[RuntimeAPI] OpenAPI 请求被拒绝: disabled remote=%s", request.remote
            )
            return _json_error("OpenAPI disabled", status=404)
        naga_routes_enabled = _naga_routes_enabled(cfg, self._ctx.naga_store)
        logger.info(
            "[RuntimeAPI] OpenAPI 请求: remote=%s naga_routes_enabled=%s",
            request.remote,
            naga_routes_enabled,
        )
        return web.json_response(_build_openapi_spec(self._ctx, request))

    async def _internal_probe_handler(self, request: web.Request) -> Response:
        _ = request
        cfg = self._ctx.config_getter()
        queue_snapshot = (
            self._ctx.queue_manager.snapshot() if self._ctx.queue_manager else {}
        )
        cognitive_queue_snapshot = (
            self._ctx.cognitive_job_queue.snapshot()
            if self._ctx.cognitive_job_queue
            else {}
        )
        memory_storage = getattr(self._ctx.ai, "memory_storage", None)
        memory_count = memory_storage.count() if memory_storage is not None else 0

        # Skills 统计
        ai = self._ctx.ai
        skills_info: dict[str, Any] = {}
        if ai is not None:
            tool_reg = getattr(ai, "tool_registry", None)
            agent_reg = getattr(ai, "agent_registry", None)
            anthropic_reg = getattr(ai, "anthropic_skill_registry", None)
            skills_info["tools"] = _registry_summary(tool_reg)
            skills_info["agents"] = _registry_summary(agent_reg)
            skills_info["anthropic_skills"] = _registry_summary(anthropic_reg)

        # 模型配置（脱敏）
        models_info: dict[str, Any] = {}
        summary_model = getattr(
            cfg,
            "summary_model",
            getattr(cfg, "agent_model", getattr(cfg, "chat_model", None)),
        )
        for label in (
            "chat_model",
            "vision_model",
            "agent_model",
            "security_model",
            "naga_model",
            "grok_model",
        ):
            mcfg = getattr(cfg, label, None)
            if mcfg is not None:
                models_info[label] = _build_internal_model_probe_payload(mcfg)
        if summary_model is not None:
            models_info["summary_model"] = _build_internal_model_probe_payload(
                summary_model
            )
        for label in ("embedding_model", "rerank_model"):
            mcfg = getattr(cfg, label, None)
            if mcfg is not None:
                models_info[label] = {
                    "model_name": getattr(mcfg, "model_name", ""),
                    "api_url": _mask_url(getattr(mcfg, "api_url", "")),
                }

        uptime_seconds = round(time.time() - _PROCESS_START_TIME, 1)
        payload = {
            "timestamp": datetime.now().isoformat(),
            "version": __version__,
            "python": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            "platform": platform.system(),
            "uptime_seconds": uptime_seconds,
            "onebot": self._ctx.onebot.connection_status()
            if self._ctx.onebot is not None
            else {},
            "queues": queue_snapshot,
            "memory": {"count": memory_count, "virtual_user_id": _VIRTUAL_USER_ID},
            "cognitive": {
                "enabled": bool(
                    self._ctx.cognitive_service and self._ctx.cognitive_service.enabled
                ),
                "queue": cognitive_queue_snapshot,
            },
            "api": {
                "enabled": bool(cfg.api.enabled),
                "host": cfg.api.host,
                "port": cfg.api.port,
                "openapi_enabled": bool(cfg.api.openapi_enabled),
            },
            "skills": skills_info,
            "models": models_info,
        }
        return web.json_response(payload)

    async def _external_probe_handler(self, request: web.Request) -> Response:
        _ = request
        cfg = self._ctx.config_getter()
        summary_model = getattr(
            cfg,
            "summary_model",
            getattr(cfg, "agent_model", getattr(cfg, "chat_model", None)),
        )
        naga_probe = (
            _probe_http_endpoint(
                name="naga_model",
                base_url=cfg.naga_model.api_url,
                api_key=cfg.naga_model.api_key,
                model_name=cfg.naga_model.model_name,
            )
            if bool(cfg.api.enabled and cfg.nagaagent_mode_enabled and cfg.naga.enabled)
            else _skipped_probe(
                name="naga_model",
                reason="naga_integration_disabled",
                model_name=cfg.naga_model.model_name,
            )
        )
        checks = [
            _probe_http_endpoint(
                name="chat_model",
                base_url=cfg.chat_model.api_url,
                api_key=cfg.chat_model.api_key,
                model_name=cfg.chat_model.model_name,
            ),
            _probe_http_endpoint(
                name="vision_model",
                base_url=cfg.vision_model.api_url,
                api_key=cfg.vision_model.api_key,
                model_name=cfg.vision_model.model_name,
            ),
            _probe_http_endpoint(
                name="security_model",
                base_url=cfg.security_model.api_url,
                api_key=cfg.security_model.api_key,
                model_name=cfg.security_model.model_name,
            ),
            naga_probe,
            _probe_http_endpoint(
                name="agent_model",
                base_url=cfg.agent_model.api_url,
                api_key=cfg.agent_model.api_key,
                model_name=cfg.agent_model.model_name,
            ),
        ]
        if summary_model is not None:
            checks.append(
                _probe_http_endpoint(
                    name="summary_model",
                    base_url=summary_model.api_url,
                    api_key=summary_model.api_key,
                    model_name=summary_model.model_name,
                )
            )
        grok_model = getattr(cfg, "grok_model", None)
        if grok_model is not None:
            checks.append(
                _probe_http_endpoint(
                    name="grok_model",
                    base_url=getattr(grok_model, "api_url", ""),
                    api_key=getattr(grok_model, "api_key", ""),
                    model_name=getattr(grok_model, "model_name", ""),
                )
            )
        checks.extend(
            [
                _probe_http_endpoint(
                    name="embedding_model",
                    base_url=cfg.embedding_model.api_url,
                    api_key=cfg.embedding_model.api_key,
                    model_name=getattr(cfg.embedding_model, "model_name", ""),
                ),
                _probe_http_endpoint(
                    name="rerank_model",
                    base_url=cfg.rerank_model.api_url,
                    api_key=cfg.rerank_model.api_key,
                    model_name=getattr(cfg.rerank_model, "model_name", ""),
                ),
                _probe_ws_endpoint(cfg.onebot_ws_url),
            ]
        )
        results = await asyncio.gather(*checks)
        ok = all(item.get("status") in {"ok", "skipped"} for item in results)
        return web.json_response(
            {
                "ok": ok,
                "timestamp": datetime.now().isoformat(),
                "results": results,
            }
        )

    async def _memory_handler(self, request: web.Request) -> Response:
        query = str(request.query.get("q", "") or "").strip().lower()
        top_k_raw = _optional_query_param(request, "top_k")
        time_from_raw = _optional_query_param(request, "time_from")
        time_to_raw = _optional_query_param(request, "time_to")
        memory_storage = getattr(self._ctx.ai, "memory_storage", None)
        if memory_storage is None:
            return _json_error("Memory storage not ready", status=503)

        limit: int | None = None
        if top_k_raw is not None:
            try:
                limit = int(top_k_raw)
            except ValueError:
                return _json_error("top_k must be an integer", status=400)
            if limit <= 0:
                return _json_error("top_k must be > 0", status=400)

        time_from_dt = _parse_query_time(time_from_raw)
        if time_from_raw is not None and time_from_dt is None:
            return _json_error("time_from must be ISO datetime", status=400)
        time_to_dt = _parse_query_time(time_to_raw)
        if time_to_raw is not None and time_to_dt is None:
            return _json_error("time_to must be ISO datetime", status=400)
        if time_from_dt and time_to_dt and time_from_dt > time_to_dt:
            time_from_dt, time_to_dt = time_to_dt, time_from_dt

        records = memory_storage.get_all()
        items: list[dict[str, Any]] = []
        for item in records:
            created_at = str(item.created_at or "").strip()
            created_dt = _parse_query_time(created_at)
            if time_from_dt and created_dt and created_dt < time_from_dt:
                continue
            if time_to_dt and created_dt and created_dt > time_to_dt:
                continue
            if (time_from_dt or time_to_dt) and created_dt is None:
                continue
            items.append(
                {
                    "uuid": item.uuid,
                    "fact": item.fact,
                    "created_at": created_at,
                }
            )
        if query:
            items = [
                item
                for item in items
                if query in str(item.get("fact", "")).lower()
                or query in str(item.get("uuid", "")).lower()
            ]

        def _created_sort_key(item: dict[str, Any]) -> float:
            created_dt = _parse_query_time(str(item.get("created_at") or ""))
            if created_dt is None:
                return float("-inf")
            with suppress(OSError, OverflowError, ValueError):
                return float(created_dt.timestamp())
            return float("-inf")

        items.sort(key=_created_sort_key)
        if limit is not None:
            items = items[:limit]

        return web.json_response(
            {
                "total": len(items),
                "items": items,
                "query": {
                    "q": query or "",
                    "top_k": limit,
                    "time_from": time_from_raw,
                    "time_to": time_to_raw,
                },
            }
        )

    async def _meme_list_handler(self, request: web.Request) -> Response:
        meme_service = self._ctx.meme_service
        if meme_service is None or not meme_service.enabled:
            return _json_error("Meme service disabled", status=400)

        def _parse_optional_bool(name: str) -> bool | None:
            raw = request.query.get(name)
            if raw is None or str(raw).strip() == "":
                return None
            return _to_bool(raw)

        page_raw = _optional_query_param(request, "page")
        page_size_raw = _optional_query_param(request, "page_size")
        top_k_raw = _optional_query_param(request, "top_k")
        query = str(request.query.get("q", "") or "").strip()
        query_mode = str(request.query.get("query_mode", "") or "").strip().lower()
        keyword_query = str(request.query.get("keyword_query", "") or "").strip()
        semantic_query = str(request.query.get("semantic_query", "") or "").strip()
        try:
            page = int(page_raw) if page_raw is not None else 1
            page_size = int(page_size_raw) if page_size_raw is not None else 50
            top_k = int(top_k_raw) if top_k_raw is not None else page_size
        except ValueError:
            return _json_error("page/page_size/top_k must be integers", status=400)
        page = max(1, page)
        page_size = max(1, min(200, page_size))
        top_k = max(1, top_k)
        sort = str(request.query.get("sort", "updated_at") or "updated_at").strip()

        enabled_filter = _parse_optional_bool("enabled")
        animated_filter = _parse_optional_bool("animated")
        pinned_filter = _parse_optional_bool("pinned")
        if not (query or keyword_query or semantic_query) and sort == "relevance":
            sort = "updated_at"

        if query or keyword_query or semantic_query:
            has_post_filter = any(
                f is not None for f in (enabled_filter, animated_filter, pinned_filter)
            )
            requested_window = max(page * page_size, top_k)
            if has_post_filter or page > 1 or sort != "relevance":
                fetch_k = min(500, max(requested_window * 4, top_k))
            else:
                fetch_k = min(500, requested_window)
            search_payload = await meme_service.search_memes(
                query,
                query_mode=query_mode or meme_service.default_query_mode,
                keyword_query=keyword_query or None,
                semantic_query=semantic_query or None,
                top_k=fetch_k,
                include_disabled=enabled_filter is not True,
                sort=sort,
            )
            filtered_items: list[dict[str, Any]] = []
            for item in list(search_payload.get("items") or []):
                if (
                    enabled_filter is not None
                    and bool(item.get("enabled")) != enabled_filter
                ):
                    continue
                if (
                    animated_filter is not None
                    and bool(item.get("is_animated")) != animated_filter
                ):
                    continue
                if (
                    pinned_filter is not None
                    and bool(item.get("pinned")) != pinned_filter
                ):
                    continue
                filtered_items.append(item)
            offset = (page - 1) * page_size
            paged_items = filtered_items[offset : offset + page_size]
            window_total = len(filtered_items)
            fetched_window_count = len(list(search_payload.get("items") or []))
            window_exhausted = fetched_window_count < fetch_k
            has_more = bool(paged_items) and (
                offset + page_size < window_total
                or (not window_exhausted and window_total >= offset + page_size)
            )
            return web.json_response(
                {
                    "ok": True,
                    "total": None,
                    "window_total": window_total,
                    "total_exact": False,
                    "page": page,
                    "page_size": page_size,
                    "has_more": has_more,
                    "query_mode": search_payload.get("query_mode"),
                    "keyword_query": search_payload.get("keyword_query"),
                    "semantic_query": search_payload.get("semantic_query"),
                    "sort": search_payload.get("sort", sort),
                    "items": paged_items,
                }
            )

        payload = await meme_service.list_memes(
            query=query,
            enabled=enabled_filter,
            animated=animated_filter,
            pinned=pinned_filter,
            sort=sort,
            page=page,
            page_size=page_size,
            summary=True,
        )
        return web.json_response(payload)

    async def _meme_stats_handler(self, request: web.Request) -> Response:
        _ = request
        meme_service = self._ctx.meme_service
        if meme_service is None or not meme_service.enabled:
            return _json_error("Meme service disabled", status=400)
        return web.json_response(await meme_service.stats())

    async def _meme_detail_handler(self, request: web.Request) -> Response:
        meme_service = self._ctx.meme_service
        if meme_service is None or not meme_service.enabled:
            return _json_error("Meme service disabled", status=400)
        uid = str(request.match_info.get("uid", "")).strip()
        detail = await meme_service.get_meme(uid)
        if detail is None:
            return _json_error("Meme not found", status=404)
        return web.json_response(detail)

    async def _meme_blob_handler(self, request: web.Request) -> Response:
        meme_service = self._ctx.meme_service
        if meme_service is None or not meme_service.enabled:
            return _json_error("Meme service disabled", status=400)
        uid = str(request.match_info.get("uid", "")).strip()
        path = await meme_service.blob_path_for_uid(uid, preview=False)
        if path is None:
            return _json_error("Meme blob not found", status=404)
        return cast(Response, web.FileResponse(path=path))

    async def _meme_preview_handler(self, request: web.Request) -> Response:
        meme_service = self._ctx.meme_service
        if meme_service is None or not meme_service.enabled:
            return _json_error("Meme service disabled", status=400)
        uid = str(request.match_info.get("uid", "")).strip()
        path = await meme_service.blob_path_for_uid(uid, preview=True)
        if path is None:
            return _json_error("Meme preview not found", status=404)
        return cast(Response, web.FileResponse(path=path))

    async def _meme_update_handler(self, request: web.Request) -> Response:
        meme_service = self._ctx.meme_service
        if meme_service is None or not meme_service.enabled:
            return _json_error("Meme service disabled", status=400)
        uid = str(request.match_info.get("uid", "")).strip()
        try:
            payload = await request.json()
        except Exception:
            return _json_error("Invalid JSON body", status=400)
        if not isinstance(payload, dict):
            return _json_error("JSON body must be an object", status=400)
        updated = await meme_service.update_meme(
            uid,
            manual_description=payload.get("manual_description"),
            tags=payload.get("tags"),
            aliases=payload.get("aliases"),
            enabled=payload.get("enabled") if "enabled" in payload else None,
            pinned=payload.get("pinned") if "pinned" in payload else None,
        )
        if updated is None:
            return _json_error("Meme not found", status=404)
        return web.json_response({"ok": True, "record": updated})

    async def _meme_delete_handler(self, request: web.Request) -> Response:
        meme_service = self._ctx.meme_service
        if meme_service is None or not meme_service.enabled:
            return _json_error("Meme service disabled", status=400)
        uid = str(request.match_info.get("uid", "")).strip()
        deleted = await meme_service.delete_meme(uid)
        if not deleted:
            return _json_error("Meme not found", status=404)
        return web.json_response({"ok": True, "uid": uid})

    async def _meme_reanalyze_handler(self, request: web.Request) -> Response:
        meme_service = self._ctx.meme_service
        if meme_service is None or not meme_service.enabled:
            return _json_error("Meme service disabled", status=400)
        uid = str(request.match_info.get("uid", "")).strip()
        job_id = await meme_service.enqueue_reanalyze(uid)
        if not job_id:
            return _json_error("Meme queue unavailable", status=503)
        return web.json_response({"ok": True, "uid": uid, "job_id": job_id})

    async def _meme_reindex_handler(self, request: web.Request) -> Response:
        meme_service = self._ctx.meme_service
        if meme_service is None or not meme_service.enabled:
            return _json_error("Meme service disabled", status=400)
        uid = str(request.match_info.get("uid", "")).strip()
        job_id = await meme_service.enqueue_reindex(uid)
        if not job_id:
            return _json_error("Meme queue unavailable", status=503)
        return web.json_response({"ok": True, "uid": uid, "job_id": job_id})

    async def _cognitive_events_handler(self, request: web.Request) -> Response:
        cognitive_service = self._ctx.cognitive_service
        if not cognitive_service or not cognitive_service.enabled:
            return _json_error("Cognitive service disabled", status=400)

        query = str(request.query.get("q", "") or "").strip()
        if not query:
            return _json_error("q is required", status=400)

        search_kwargs: dict[str, Any] = {"query": query}
        for key in (
            "target_user_id",
            "target_group_id",
            "sender_id",
            "request_type",
            "top_k",
            "time_from",
            "time_to",
        ):
            value = _optional_query_param(request, key)
            if value is not None:
                search_kwargs[key] = value

        results = await cognitive_service.search_events(**search_kwargs)
        return web.json_response({"count": len(results), "items": results})

    async def _cognitive_profiles_handler(self, request: web.Request) -> Response:
        cognitive_service = self._ctx.cognitive_service
        if not cognitive_service or not cognitive_service.enabled:
            return _json_error("Cognitive service disabled", status=400)

        query = str(request.query.get("q", "") or "").strip()
        if not query:
            return _json_error("q is required", status=400)

        search_kwargs: dict[str, Any] = {"query": query}
        entity_type = _optional_query_param(request, "entity_type")
        if entity_type is not None:
            search_kwargs["entity_type"] = entity_type
        top_k = _optional_query_param(request, "top_k")
        if top_k is not None:
            search_kwargs["top_k"] = top_k

        results = await cognitive_service.search_profiles(**search_kwargs)
        return web.json_response({"count": len(results), "items": results})

    async def _cognitive_profile_handler(self, request: web.Request) -> Response:
        cognitive_service = self._ctx.cognitive_service
        if not cognitive_service or not cognitive_service.enabled:
            return _json_error("Cognitive service disabled", status=400)

        entity_type = str(request.match_info.get("entity_type", "")).strip()
        entity_id = str(request.match_info.get("entity_id", "")).strip()
        if not entity_type or not entity_id:
            return _json_error("entity_type/entity_id are required", status=400)

        profile = await cognitive_service.get_profile(entity_type, entity_id)
        return web.json_response(
            {
                "entity_type": entity_type,
                "entity_id": entity_id,
                "profile": profile or "",
                "found": bool(profile),
            }
        )

    async def _run_webui_chat(
        self,
        *,
        text: str,
        send_output: Callable[[int, str], Awaitable[None]],
    ) -> str:
        cfg = self._ctx.config_getter()
        permission_sender_id = int(cfg.superadmin_qq)
        webui_scope_key = build_attachment_scope(
            user_id=_VIRTUAL_USER_ID,
            request_type="private",
            webui_session=True,
        )
        input_segments = message_to_segments(text)
        registered_input = await register_message_attachments(
            registry=self._ctx.ai.attachment_registry,
            segments=input_segments,
            scope_key=webui_scope_key,
            resolve_image_url=self._ctx.onebot.get_image,
            get_forward_messages=self._ctx.onebot.get_forward_msg,
        )
        normalized_text = registered_input.normalized_text or text
        await self._ctx.history_manager.add_private_message(
            user_id=_VIRTUAL_USER_ID,
            text_content=normalized_text,
            display_name=_VIRTUAL_USER_NAME,
            user_name=_VIRTUAL_USER_NAME,
            attachments=registered_input.attachments,
        )

        command = self._ctx.command_dispatcher.parse_command(normalized_text)
        if command:
            await self._ctx.command_dispatcher.dispatch_private(
                user_id=_VIRTUAL_USER_ID,
                sender_id=permission_sender_id,
                command=command,
                send_private_callback=send_output,
                is_webui_session=True,
            )
            return "command"

        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        attachment_xml = (
            f"\n{attachment_refs_to_xml(registered_input.attachments)}"
            if registered_input.attachments
            else ""
        )
        full_question = f"""<message sender="{escape_xml_attr(_VIRTUAL_USER_NAME)}" sender_id="{escape_xml_attr(_VIRTUAL_USER_ID)}" location="WebUI私聊" time="{escape_xml_attr(current_time)}">
 <content>{escape_xml_text(normalized_text)}</content>{attachment_xml}
 </message>

【WebUI 会话】
这是一条来自 WebUI 控制台的会话请求。
会话身份：虚拟用户 system(42)。
权限等级：superadmin（你可按最高管理权限处理）。
请正常进行私聊对话；如果需要结束会话，调用 end 工具。"""
        virtual_sender = _WebUIVirtualSender(
            _VIRTUAL_USER_ID, send_output, onebot=self._ctx.onebot
        )

        async def _get_recent_cb(
            chat_id: str, msg_type: str, start: int, end: int
        ) -> list[dict[str, Any]]:
            return await get_recent_messages_prefer_local(
                chat_id=chat_id,
                msg_type=msg_type,
                start=start,
                end=end,
                onebot_client=self._ctx.onebot,
                history_manager=self._ctx.history_manager,
                bot_qq=cfg.bot_qq,
                attachment_registry=getattr(self._ctx.ai, "attachment_registry", None),
            )

        async with RequestContext(
            request_type="private",
            user_id=_VIRTUAL_USER_ID,
            sender_id=permission_sender_id,
        ) as ctx:
            # 与 ai_coordinator 保持一致：通过 collect_context_resources 自动注入
            ai_client = self._ctx.ai
            memory_storage = self._ctx.ai.memory_storage
            runtime_config = self._ctx.ai.runtime_config
            sender = virtual_sender
            history_manager = self._ctx.history_manager
            onebot_client = self._ctx.onebot
            scheduler = self._ctx.scheduler

            def send_message_callback(
                msg: str, reply_to: int | None = None
            ) -> Awaitable[None]:
                _ = reply_to
                return send_output(_VIRTUAL_USER_ID, msg)

            get_recent_messages_callback = _get_recent_cb
            get_image_url_callback = self._ctx.onebot.get_image
            get_forward_msg_callback = self._ctx.onebot.get_forward_msg
            resource_vars = dict(globals())
            resource_vars.update(locals())
            resources = collect_context_resources(resource_vars)
            for key, value in resources.items():
                if value is not None:
                    ctx.set_resource(key, value)
            ctx.set_resource("queue_lane", QUEUE_LANE_SUPERADMIN)
            ctx.set_resource("webui_session", True)
            ctx.set_resource("webui_permission", "superadmin")

            result = await self._ctx.ai.ask(
                full_question,
                send_message_callback=send_message_callback,
                get_recent_messages_callback=get_recent_messages_callback,
                get_image_url_callback=get_image_url_callback,
                get_forward_msg_callback=get_forward_msg_callback,
                sender=sender,
                history_manager=history_manager,
                onebot_client=onebot_client,
                scheduler=scheduler,
                extra_context={
                    "is_private_chat": True,
                    "request_type": "private",
                    "user_id": _VIRTUAL_USER_ID,
                    "sender_name": _VIRTUAL_USER_NAME,
                    "webui_session": True,
                    "webui_permission": "superadmin",
                },
            )

        final_reply = str(result or "").strip()
        if final_reply:
            await send_output(_VIRTUAL_USER_ID, final_reply)

        return "chat"

    async def _chat_history_handler(self, request: web.Request) -> Response:
        limit_raw = str(request.query.get("limit", "200") or "200").strip()
        try:
            limit = int(limit_raw)
        except ValueError:
            limit = 200
        limit = max(1, min(limit, 500))

        getter = getattr(self._ctx.history_manager, "get_recent_private", None)
        if not callable(getter):
            return _json_error("History manager not ready", status=503)

        records = getter(_VIRTUAL_USER_ID, limit)
        items: list[dict[str, Any]] = []
        for item in records:
            if not isinstance(item, dict):
                continue
            content = str(item.get("message", "")).strip()
            if not content:
                continue
            display_name = str(item.get("display_name", "")).strip().lower()
            role = "bot" if display_name == "bot" else "user"
            items.append(
                {
                    "role": role,
                    "content": content,
                    "timestamp": str(item.get("timestamp", "") or "").strip(),
                }
            )

        return web.json_response(
            {
                "virtual_user_id": _VIRTUAL_USER_ID,
                "permission": "superadmin",
                "count": len(items),
                "items": items,
            }
        )

    async def _chat_handler(self, request: web.Request) -> web.StreamResponse:
        try:
            body = await request.json()
        except Exception:
            return _json_error("Invalid JSON", status=400)

        text = str(body.get("message", "") or "").strip()
        if not text:
            return _json_error("message is required", status=400)

        stream = _to_bool(body.get("stream"))
        outputs: list[str] = []
        webui_scope_key = build_attachment_scope(
            user_id=_VIRTUAL_USER_ID,
            request_type="private",
            webui_session=True,
        )

        async def _capture_private_message(user_id: int, message: str) -> None:
            _ = user_id
            content = str(message or "").strip()
            if not content:
                return
            rendered = await render_message_with_pic_placeholders(
                content,
                registry=self._ctx.ai.attachment_registry,
                scope_key=webui_scope_key,
                strict=False,
            )
            if not rendered.delivery_text.strip():
                return
            outputs.append(rendered.delivery_text)
            await self._ctx.history_manager.add_private_message(
                user_id=_VIRTUAL_USER_ID,
                text_content=rendered.history_text,
                display_name="Bot",
                user_name="Bot",
                attachments=rendered.attachments,
            )

        if not stream:
            try:
                mode = await self._run_webui_chat(
                    text=text, send_output=_capture_private_message
                )
            except Exception as exc:
                logger.exception("[RuntimeAPI] chat failed: %s", exc)
                return _json_error("Chat failed", status=502)
            return web.json_response(_build_chat_response_payload(mode, outputs))

        response = web.StreamResponse(
            status=200,
            reason="OK",
            headers={
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
            },
        )
        await response.prepare(request)

        message_queue: asyncio.Queue[str] = asyncio.Queue()

        async def _capture_private_message_stream(user_id: int, message: str) -> None:
            output_count = len(outputs)
            await _capture_private_message(user_id, message)
            if len(outputs) <= output_count:
                return
            content = outputs[-1].strip()
            if content:
                await message_queue.put(content)

        task = asyncio.create_task(
            self._run_webui_chat(text=text, send_output=_capture_private_message_stream)
        )
        mode = "chat"
        client_disconnected = False
        try:
            await response.write(
                _sse_event(
                    "meta",
                    {
                        "virtual_user_id": _VIRTUAL_USER_ID,
                        "permission": "superadmin",
                    },
                )
            )

            while True:
                if request.transport is None or request.transport.is_closing():
                    client_disconnected = True
                    break
                if task.done() and message_queue.empty():
                    break
                try:
                    message = await asyncio.wait_for(
                        message_queue.get(),
                        timeout=_CHAT_SSE_KEEPALIVE_SECONDS,
                    )
                    await response.write(_sse_event("message", {"content": message}))
                except asyncio.TimeoutError:
                    await response.write(b": keep-alive\n\n")

            if client_disconnected:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
                return response

            mode = await task
            await response.write(
                _sse_event("done", _build_chat_response_payload(mode, outputs))
            )
        except asyncio.CancelledError:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
            raise
        except (ConnectionResetError, RuntimeError):
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        except Exception as exc:
            logger.exception("[RuntimeAPI] chat stream failed: %s", exc)
            if not task.done():
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
            with suppress(Exception):
                await response.write(_sse_event("error", {"error": str(exc)}))
        finally:
            with suppress(Exception):
                await response.write_eof()

        return response

    # ------------------------------------------------------------------
    # Tool Invoke API
    # ------------------------------------------------------------------

    def _get_filtered_tools(self) -> list[dict[str, Any]]:
        """按配置过滤可用工具，返回 OpenAI function calling schema 列表。"""
        cfg = self._ctx.config_getter()
        api_cfg = cfg.api
        ai = self._ctx.ai
        if ai is None:
            return []

        tool_reg = getattr(ai, "tool_registry", None)
        agent_reg = getattr(ai, "agent_registry", None)

        all_schemas: list[dict[str, Any]] = []
        if tool_reg is not None:
            all_schemas.extend(tool_reg.get_tools_schema())

        # 收集 agent schema 并缓存名称集合（避免重复调用）
        agent_names: set[str] = set()
        if agent_reg is not None:
            agent_schemas = agent_reg.get_agents_schema()
            all_schemas.extend(agent_schemas)
            for schema in agent_schemas:
                func = schema.get("function", {})
                name = str(func.get("name", ""))
                if name:
                    agent_names.add(name)

        denylist: set[str] = set(api_cfg.tool_invoke_denylist)
        allowlist: set[str] = set(api_cfg.tool_invoke_allowlist)
        expose = api_cfg.tool_invoke_expose

        def _get_name(schema: dict[str, Any]) -> str:
            func = schema.get("function", {})
            return str(func.get("name", ""))

        # 1. 先排除黑名单
        if denylist:
            all_schemas = [s for s in all_schemas if _get_name(s) not in denylist]

        # 2. 白名单非空时仅保留匹配项
        if allowlist:
            return [s for s in all_schemas if _get_name(s) in allowlist]

        # 3. 按 expose 过滤
        if expose == "all":
            return all_schemas

        def _is_tool(name: str) -> bool:
            return "." not in name and name not in agent_names

        def _is_toolset(name: str) -> bool:
            return "." in name and not name.startswith("mcp.")

        filtered: list[dict[str, Any]] = []
        for schema in all_schemas:
            name = _get_name(schema)
            if not name:
                continue
            if expose == "tools" and _is_tool(name):
                filtered.append(schema)
            elif expose == "toolsets" and _is_toolset(name):
                filtered.append(schema)
            elif expose == "tools+toolsets" and (_is_tool(name) or _is_toolset(name)):
                filtered.append(schema)
            elif expose == "agents" and name in agent_names:
                filtered.append(schema)

        return filtered

    def _get_agent_tool_names(self) -> set[str]:
        ai = self._ctx.ai
        if ai is None:
            return set()

        agent_reg = getattr(ai, "agent_registry", None)
        if agent_reg is None:
            return set()

        agent_names: set[str] = set()
        for schema in agent_reg.get_agents_schema():
            func = schema.get("function", {})
            name = str(func.get("name", ""))
            if name:
                agent_names.add(name)
        return agent_names

    def _resolve_tool_invoke_timeout(
        self, tool_name: str, timeout: int
    ) -> float | None:
        if tool_name in self._get_agent_tool_names():
            return None
        return float(timeout)

    async def _await_tool_invoke_result(
        self,
        awaitable: Awaitable[Any],
        *,
        timeout: float | None,
    ) -> Any:
        if timeout is None or timeout <= 0:
            return await awaitable
        try:
            return await asyncio.wait_for(awaitable, timeout=timeout)
        except asyncio.TimeoutError as exc:
            raise _ToolInvokeExecutionTimeoutError from exc

    async def _tools_list_handler(self, request: web.Request) -> Response:
        _ = request
        cfg = self._ctx.config_getter()
        if not cfg.api.tool_invoke_enabled:
            return _json_error("Tool invoke API is disabled", status=403)

        tools = self._get_filtered_tools()
        return web.json_response({"count": len(tools), "tools": tools})

    async def _tools_invoke_handler(self, request: web.Request) -> Response:
        cfg = self._ctx.config_getter()
        if not cfg.api.tool_invoke_enabled:
            return _json_error("Tool invoke API is disabled", status=403)

        try:
            body = await request.json()
        except Exception:
            return _json_error("Invalid JSON", status=400)

        if not isinstance(body, dict):
            return _json_error("Request body must be a JSON object", status=400)

        tool_name = str(body.get("tool_name", "") or "").strip()
        if not tool_name:
            return _json_error("tool_name is required", status=400)

        args = body.get("args")
        if not isinstance(args, dict):
            return _json_error("args must be a JSON object", status=400)

        # 验证工具是否在允许列表中
        filtered_tools = self._get_filtered_tools()
        available_names: set[str] = set()
        for schema in filtered_tools:
            func = schema.get("function", {})
            name = str(func.get("name", ""))
            if name:
                available_names.add(name)

        if tool_name not in available_names:
            caller_ip = request.remote or "unknown"
            logger.warning(
                "[ToolInvoke] 请求拒绝: tool=%s reason=not_available caller_ip=%s",
                tool_name,
                caller_ip,
            )
            return _json_error(f"Tool '{tool_name}' is not available", status=404)

        # 解析回调配置
        callback_cfg = body.get("callback")
        use_callback = False
        callback_url = ""
        callback_headers: dict[str, str] = {}
        if isinstance(callback_cfg, dict) and _to_bool(callback_cfg.get("enabled")):
            callback_url = str(callback_cfg.get("url", "") or "").strip()
            if not callback_url:
                return _json_error(
                    "callback.url is required when callback is enabled",
                    status=400,
                )
            url_error = _validate_callback_url(callback_url)
            if url_error:
                return _json_error(url_error, status=400)
            raw_headers = callback_cfg.get("headers")
            if isinstance(raw_headers, dict):
                callback_headers = {str(k): str(v) for k, v in raw_headers.items()}
            use_callback = True

        request_id = _uuid.uuid4().hex
        caller_ip = request.remote or "unknown"
        logger.info(
            "[ToolInvoke] 收到请求: request_id=%s tool=%s caller_ip=%s",
            request_id,
            tool_name,
            caller_ip,
        )

        if use_callback:
            # 异步执行 + 回调
            task = asyncio.create_task(
                self._execute_and_callback(
                    request_id=request_id,
                    tool_name=tool_name,
                    args=args,
                    body_context=body.get("context"),
                    callback_url=callback_url,
                    callback_headers=callback_headers,
                    timeout=cfg.api.tool_invoke_timeout,
                    callback_timeout=cfg.api.tool_invoke_callback_timeout,
                )
            )
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)
            return web.json_response(
                {
                    "ok": True,
                    "request_id": request_id,
                    "tool_name": tool_name,
                    "status": "accepted",
                }
            )

        # 同步执行
        result = await self._execute_tool_invoke(
            request_id=request_id,
            tool_name=tool_name,
            args=args,
            body_context=body.get("context"),
            timeout=cfg.api.tool_invoke_timeout,
        )
        return web.json_response(result)

    async def _execute_tool_invoke(
        self,
        *,
        request_id: str,
        tool_name: str,
        args: dict[str, Any],
        body_context: Any,
        timeout: int,
    ) -> dict[str, Any]:
        """执行工具调用并返回结果字典。"""
        ai = self._ctx.ai
        if ai is None:
            return {
                "ok": False,
                "request_id": request_id,
                "tool_name": tool_name,
                "error": "AI client not ready",
                "duration_ms": 0,
            }

        # 解析请求上下文
        ctx_data: dict[str, Any] = {}
        if isinstance(body_context, dict):
            ctx_data = body_context
        request_type = str(ctx_data.get("request_type", "api") or "api")
        group_id = ctx_data.get("group_id")
        user_id = ctx_data.get("user_id")
        sender_id = ctx_data.get("sender_id")

        args_keys = list(args.keys())
        logger.info(
            "[ToolInvoke] 开始执行: request_id=%s tool=%s args_keys=%s",
            request_id,
            tool_name,
            args_keys,
        )

        start = time.perf_counter()
        effective_timeout = self._resolve_tool_invoke_timeout(tool_name, timeout)
        try:
            async with RequestContext(
                request_type=request_type,
                group_id=int(group_id) if group_id is not None else None,
                user_id=int(user_id) if user_id is not None else None,
                sender_id=int(sender_id) if sender_id is not None else None,
            ) as ctx:
                # 注入核心服务资源
                if self._ctx.sender is not None:
                    ctx.set_resource("sender", self._ctx.sender)
                if self._ctx.history_manager is not None:
                    ctx.set_resource("history_manager", self._ctx.history_manager)
                runtime_config = getattr(ai, "runtime_config", None)
                if runtime_config is not None:
                    ctx.set_resource("runtime_config", runtime_config)
                memory_storage = getattr(ai, "memory_storage", None)
                if memory_storage is not None:
                    ctx.set_resource("memory_storage", memory_storage)
                if self._ctx.onebot is not None:
                    ctx.set_resource("onebot_client", self._ctx.onebot)
                if self._ctx.scheduler is not None:
                    ctx.set_resource("scheduler", self._ctx.scheduler)
                if self._ctx.cognitive_service is not None:
                    ctx.set_resource("cognitive_service", self._ctx.cognitive_service)
                if self._ctx.meme_service is not None:
                    ctx.set_resource("meme_service", self._ctx.meme_service)

                tool_context: dict[str, Any] = {
                    "request_type": request_type,
                    "request_id": request_id,
                }
                if group_id is not None:
                    tool_context["group_id"] = int(group_id)
                if user_id is not None:
                    tool_context["user_id"] = int(user_id)
                if sender_id is not None:
                    tool_context["sender_id"] = int(sender_id)

                tool_manager = getattr(ai, "tool_manager", None)
                if tool_manager is None:
                    raise RuntimeError("ToolManager not available")

                raw_result = await self._await_tool_invoke_result(
                    tool_manager.execute_tool(tool_name, args, tool_context),
                    timeout=effective_timeout,
                )

            elapsed_ms = round((time.perf_counter() - start) * 1000, 1)
            result_str = str(raw_result or "")
            logger.info(
                "[ToolInvoke] 执行完成: request_id=%s tool=%s ok=true "
                "duration_ms=%s result_len=%d",
                request_id,
                tool_name,
                elapsed_ms,
                len(result_str),
            )
            return {
                "ok": True,
                "request_id": request_id,
                "tool_name": tool_name,
                "result": result_str,
                "duration_ms": elapsed_ms,
            }

        except _ToolInvokeExecutionTimeoutError:
            elapsed_ms = round((time.perf_counter() - start) * 1000, 1)
            logger.warning(
                "[ToolInvoke] 执行超时: request_id=%s tool=%s timeout=%ds",
                request_id,
                tool_name,
                timeout,
            )
            return {
                "ok": False,
                "request_id": request_id,
                "tool_name": tool_name,
                "error": f"Execution timed out after {timeout}s",
                "duration_ms": elapsed_ms,
            }
        except Exception as exc:
            elapsed_ms = round((time.perf_counter() - start) * 1000, 1)
            logger.exception(
                "[ToolInvoke] 执行失败: request_id=%s tool=%s error=%s",
                request_id,
                tool_name,
                exc,
            )
            return {
                "ok": False,
                "request_id": request_id,
                "tool_name": tool_name,
                "error": str(exc),
                "duration_ms": elapsed_ms,
            }

    async def _execute_and_callback(
        self,
        *,
        request_id: str,
        tool_name: str,
        args: dict[str, Any],
        body_context: Any,
        callback_url: str,
        callback_headers: dict[str, str],
        timeout: int,
        callback_timeout: int,
    ) -> None:
        """异步执行工具并发送回调。"""
        result = await self._execute_tool_invoke(
            request_id=request_id,
            tool_name=tool_name,
            args=args,
            body_context=body_context,
            timeout=timeout,
        )

        payload = {
            "request_id": result["request_id"],
            "tool_name": result["tool_name"],
            "ok": result["ok"],
            "result": result.get("result"),
            "duration_ms": result.get("duration_ms", 0),
            "error": result.get("error"),
        }

        try:
            cb_timeout = ClientTimeout(total=callback_timeout)
            async with ClientSession(timeout=cb_timeout) as session:
                # aiohttp json= 自动设置 Content-Type，无需手动指定
                async with session.post(
                    callback_url,
                    json=payload,
                    headers=callback_headers or None,
                ) as resp:
                    logger.info(
                        "[ToolInvoke] 回调发送: request_id=%s url=%s status=%d",
                        request_id,
                        _mask_url(callback_url),
                        resp.status,
                    )
        except Exception as exc:
            logger.warning(
                "[ToolInvoke] 回调失败: request_id=%s url=%s error=%s",
                request_id,
                _mask_url(callback_url),
                exc,
            )

    # ------------------------------------------------------------------
    # Naga Bind / Send / Unbind API
    # ------------------------------------------------------------------

    def _verify_naga_api_key(self, request: web.Request) -> str | None:
        """校验 Naga 共享密钥，返回错误信息或 None 表示通过。"""
        cfg = self._ctx.config_getter()
        expected = cfg.naga.api_key
        if not expected:
            return "naga api_key not configured"
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return "missing or invalid Authorization header"
        provided = auth_header[7:]
        import secrets as _secrets

        if not _secrets.compare_digest(provided, expected):
            return "invalid api_key"
        return None

    async def _naga_bind_callback_handler(self, request: web.Request) -> Response:
        """POST /api/v1/naga/bind/callback — Naga 绑定回调。"""
        trace_id = _uuid.uuid4().hex[:8]
        auth_err = self._verify_naga_api_key(request)
        if auth_err is not None:
            logger.warning(
                "[NagaBindCallback] 鉴权失败: trace=%s remote=%s err=%s",
                trace_id,
                getattr(request, "remote", None),
                auth_err,
            )
            return _json_error("Unauthorized", status=401)

        try:
            body = await request.json()
        except Exception:
            return _json_error("Invalid JSON", status=400)

        bind_uuid = str(body.get("bind_uuid", "") or "").strip()
        naga_id = str(body.get("naga_id", "") or "").strip()
        status = str(body.get("status", "") or "").strip().lower()
        delivery_signature = str(body.get("delivery_signature", "") or "").strip()
        reason = str(body.get("reason", "") or "").strip()
        if not bind_uuid or not naga_id:
            return _json_error("bind_uuid and naga_id are required", status=400)
        if status not in {"approved", "rejected"}:
            return _json_error("status must be 'approved' or 'rejected'", status=400)
        logger.info(
            "[NagaBindCallback] 请求开始: trace=%s remote=%s naga_id=%s bind_uuid=%s status=%s reason=%s signature=%s",
            trace_id,
            getattr(request, "remote", None),
            naga_id,
            bind_uuid,
            status,
            _short_text_preview(reason, limit=60),
            delivery_signature[:12] + "..." if delivery_signature else "",
        )

        naga_store = self._ctx.naga_store
        if naga_store is None:
            return _json_error("Naga integration not available", status=503)

        sender = self._ctx.sender
        if status == "approved":
            if not delivery_signature:
                return _json_error(
                    "delivery_signature is required when approved", status=400
                )
            binding, created, err = await naga_store.activate_binding(
                bind_uuid=bind_uuid,
                naga_id=naga_id,
                delivery_signature=delivery_signature,
            )
            if err:
                logger.warning(
                    "[NagaBindCallback] 激活失败: trace=%s naga_id=%s bind_uuid=%s err=%s",
                    trace_id,
                    naga_id,
                    bind_uuid,
                    err.message,
                )
                return _json_error(err.message, status=err.http_status)
            logger.info(
                "[NagaBindCallback] 激活完成: trace=%s naga_id=%s bind_uuid=%s created=%s qq=%s",
                trace_id,
                naga_id,
                bind_uuid,
                created,
                binding.qq_id if binding is not None else "",
            )
            if created and binding is not None and sender is not None:
                try:
                    await sender.send_private_message(
                        binding.qq_id,
                        f"🎉 你的 Naga 绑定已生效\nnaga_id: {naga_id}",
                    )
                except Exception as exc:
                    logger.warning("[NagaBindCallback] 通知绑定成功失败: %s", exc)
            return web.json_response(
                {
                    "ok": True,
                    "status": "approved",
                    "idempotent": not created,
                    "naga_id": naga_id,
                    "bind_uuid": bind_uuid,
                }
            )

        pending, removed, err = await naga_store.reject_binding(
            bind_uuid=bind_uuid,
            naga_id=naga_id,
            reason=reason,
        )
        if err:
            logger.warning(
                "[NagaBindCallback] 拒绝失败: trace=%s naga_id=%s bind_uuid=%s err=%s",
                trace_id,
                naga_id,
                bind_uuid,
                err.message,
            )
            return _json_error(err.message, status=err.http_status)
        logger.info(
            "[NagaBindCallback] 拒绝完成: trace=%s naga_id=%s bind_uuid=%s removed=%s qq=%s",
            trace_id,
            naga_id,
            bind_uuid,
            removed,
            pending.qq_id if pending is not None else "",
        )
        if removed and pending is not None and sender is not None:
            try:
                detail = f"\n原因: {reason}" if reason else ""
                await sender.send_private_message(
                    pending.qq_id,
                    f"❌ 你的 Naga 绑定被远端拒绝\nnaga_id: {naga_id}{detail}",
                )
            except Exception as exc:
                logger.warning("[NagaBindCallback] 通知绑定拒绝失败: %s", exc)
        return web.json_response(
            {
                "ok": True,
                "status": "rejected",
                "idempotent": not removed,
                "naga_id": naga_id,
                "bind_uuid": bind_uuid,
            }
        )

    async def _naga_messages_send_handler(self, request: web.Request) -> Response:
        """POST /api/v1/naga/messages/send — 验签后发送消息。"""
        from Undefined.api.naga_store import mask_token

        trace_id = _uuid.uuid4().hex[:8]
        auth_err = self._verify_naga_api_key(request)
        if auth_err is not None:
            logger.warning("[NagaSend] 鉴权失败: trace=%s err=%s", trace_id, auth_err)
            return _json_error("Unauthorized", status=401)

        try:
            body = await request.json()
        except Exception:
            return _json_error("Invalid JSON", status=400)

        bind_uuid = str(body.get("bind_uuid", "") or "").strip()
        naga_id = str(body.get("naga_id", "") or "").strip()
        delivery_signature = str(body.get("delivery_signature", "") or "").strip()
        request_uuid = str(body.get("uuid", "") or "").strip()
        target = body.get("target")
        message = body.get("message")
        if not bind_uuid or not naga_id or not delivery_signature:
            return _json_error(
                "bind_uuid, naga_id and delivery_signature are required",
                status=400,
            )
        if not isinstance(target, dict):
            return _json_error("target object is required", status=400)
        if not isinstance(message, dict):
            return _json_error("message object is required", status=400)

        raw_target_qq = target.get("qq_id")
        raw_target_group = target.get("group_id")
        if raw_target_qq is None or raw_target_group is None:
            return _json_error(
                "target.qq_id and target.group_id are required", status=400
            )
        try:
            target_qq = int(raw_target_qq)
            target_group = int(raw_target_group)
        except Exception:
            return _json_error(
                "target.qq_id and target.group_id must be integers", status=400
            )
        mode = str(target.get("mode", "") or "").strip().lower()
        if mode not in {"private", "group", "both"}:
            return _json_error(
                "target.mode must be 'private', 'group', or 'both'", status=400
            )

        fmt = str(message.get("format", "text") or "text").strip().lower()
        content = str(message.get("content", "") or "").strip()
        if fmt not in {"text", "markdown", "html"}:
            return _json_error(
                "message.format must be 'text', 'markdown', or 'html'", status=400
            )
        if not content:
            return _json_error("message.content is required", status=400)

        message_key = _naga_message_digest(
            bind_uuid=bind_uuid,
            naga_id=naga_id,
            target_qq=target_qq,
            target_group=target_group,
            mode=mode,
            message_format=fmt,
            content=content,
        )
        logger.info(
            "[NagaSend] 请求开始: trace=%s remote=%s naga_id=%s bind_uuid=%s request_uuid=%s mode=%s fmt=%s qq=%s group=%s key=%s content_len=%s preview=%s signature=%s",
            trace_id,
            getattr(request, "remote", None),
            naga_id,
            bind_uuid,
            request_uuid,
            mode,
            fmt,
            target_qq,
            target_group,
            message_key,
            len(content),
            _short_text_preview(content),
            mask_token(delivery_signature),
        )
        if mode == "both":
            logger.warning(
                "[NagaSend] 上游请求显式要求双路投递: trace=%s naga_id=%s bind_uuid=%s request_uuid=%s key=%s",
                trace_id,
                naga_id,
                bind_uuid,
                request_uuid,
                message_key,
            )
        inflight_count = await self._track_naga_send_start(message_key)
        if inflight_count > 1:
            logger.warning(
                "[NagaSend] 检测到相同 payload 并发请求: trace=%s naga_id=%s bind_uuid=%s request_uuid=%s key=%s inflight=%s",
                trace_id,
                naga_id,
                bind_uuid,
                request_uuid,
                message_key,
                inflight_count,
            )
        try:
            if request_uuid:
                dedupe_action, dedupe_value = await self._register_naga_request_uuid(
                    request_uuid, message_key
                )
                if dedupe_action == "conflict":
                    logger.warning(
                        "[NagaSend] uuid 与历史 payload 冲突: trace=%s naga_id=%s bind_uuid=%s uuid=%s key=%s",
                        trace_id,
                        naga_id,
                        bind_uuid,
                        request_uuid,
                        message_key,
                    )
                    return _json_error("uuid reused with different payload", status=409)
                if dedupe_action == "cached":
                    cached_status, cached_payload = dedupe_value
                    logger.warning(
                        "[NagaSend] 命中已完成幂等结果，直接复用: trace=%s naga_id=%s bind_uuid=%s request_uuid=%s key=%s",
                        trace_id,
                        naga_id,
                        bind_uuid,
                        request_uuid,
                        message_key,
                    )
                    return web.json_response(
                        deepcopy(cached_payload),
                        status=int(cached_status),
                    )
                if dedupe_action == "await":
                    wait_future = dedupe_value
                    logger.warning(
                        "[NagaSend] 命中进行中幂等请求，等待首个结果: trace=%s naga_id=%s bind_uuid=%s request_uuid=%s key=%s",
                        trace_id,
                        naga_id,
                        bind_uuid,
                        request_uuid,
                        message_key,
                    )
                    cached_status, cached_payload = await wait_future
                    return web.json_response(
                        deepcopy(cached_payload),
                        status=int(cached_status),
                    )

            response = await self._naga_messages_send_impl(
                naga_id=naga_id,
                bind_uuid=bind_uuid,
                delivery_signature=delivery_signature,
                target_qq=target_qq,
                target_group=target_group,
                mode=mode,
                message_format=fmt,
                content=content,
                trace_id=trace_id,
                message_key=message_key,
            )
            if request_uuid:
                await self._finish_naga_request_uuid(
                    request_uuid,
                    message_key,
                    status=response.status,
                    payload=_parse_response_payload(response),
                )
            return response
        except Exception as exc:
            if request_uuid:
                await self._fail_naga_request_uuid(request_uuid, message_key, exc)
            raise
        finally:
            remaining = await self._track_naga_send_done(message_key)
            logger.info(
                "[NagaSend] 请求退出: trace=%s naga_id=%s bind_uuid=%s request_uuid=%s key=%s inflight_remaining=%s",
                trace_id,
                naga_id,
                bind_uuid,
                request_uuid,
                message_key,
                remaining,
            )

    async def _naga_messages_send_impl(
        self,
        *,
        naga_id: str,
        bind_uuid: str,
        delivery_signature: str,
        target_qq: int,
        target_group: int,
        mode: str,
        message_format: str,
        content: str,
        trace_id: str,
        message_key: str,
    ) -> Response:
        from Undefined.api.naga_store import mask_token

        naga_store = self._ctx.naga_store
        if naga_store is None:
            logger.warning(
                "[NagaSend] NagaStore 不可用: trace=%s naga_id=%s bind_uuid=%s",
                trace_id,
                naga_id,
                bind_uuid,
            )
            return _json_error("Naga integration not available", status=503)

        binding, err_msg = await naga_store.acquire_delivery(
            naga_id=naga_id,
            bind_uuid=bind_uuid,
            delivery_signature=delivery_signature,
        )
        if binding is None:
            logger.warning(
                "[NagaSend] 签名校验失败: trace=%s naga_id=%s bind_uuid=%s reason=%s signature=%s",
                trace_id,
                naga_id,
                bind_uuid,
                err_msg.message if err_msg is not None else "unknown_error",
                mask_token(delivery_signature),
            )
            return _json_error(
                err_msg.message if err_msg is not None else "delivery not available",
                status=err_msg.http_status if err_msg is not None else 403,
            )

        logger.info(
            "[NagaSend] 投递凭证已占用: trace=%s naga_id=%s bind_uuid=%s key=%s qq=%s group=%s",
            trace_id,
            naga_id,
            bind_uuid,
            message_key,
            binding.qq_id,
            binding.group_id,
        )
        try:
            if target_qq != binding.qq_id or target_group != binding.group_id:
                logger.warning(
                    "[NagaSend] 目标不匹配: trace=%s naga_id=%s bind_uuid=%s target_qq=%s target_group=%s bound_qq=%s bound_group=%s",
                    trace_id,
                    naga_id,
                    bind_uuid,
                    target_qq,
                    target_group,
                    binding.qq_id,
                    binding.group_id,
                )
                return _json_error("target does not match bound qq/group", status=403)

            cfg = self._ctx.config_getter()
            if mode == "group" and binding.group_id not in cfg.naga.allowed_groups:
                logger.warning(
                    "[NagaSend] 群投递被策略拒绝: trace=%s naga_id=%s bind_uuid=%s group=%s",
                    trace_id,
                    naga_id,
                    bind_uuid,
                    binding.group_id,
                )
                return _json_error(
                    "bound group is not in naga.allowed_groups", status=403
                )

            sender = self._ctx.sender
            if sender is None:
                logger.warning(
                    "[NagaSend] sender 不可用: trace=%s naga_id=%s bind_uuid=%s",
                    trace_id,
                    naga_id,
                    bind_uuid,
                )
                return _json_error("sender not available", status=503)

            moderation: dict[str, Any]
            naga_cfg = getattr(cfg, "naga", None)
            moderation_enabled = bool(getattr(naga_cfg, "moderation_enabled", True))
            security = getattr(self._ctx.command_dispatcher, "security", None)
            if not moderation_enabled:
                moderation = {
                    "status": "skipped_disabled",
                    "blocked": False,
                    "categories": [],
                    "message": "Naga moderation disabled by config; message sent without moderation block",
                    "model_name": "",
                }
                logger.warning(
                    "[NagaSend] 审核已禁用，直接放行: trace=%s naga_id=%s bind_uuid=%s key=%s",
                    trace_id,
                    naga_id,
                    bind_uuid,
                    message_key,
                )
            elif security is None or not hasattr(security, "moderate_naga_message"):
                moderation = {
                    "status": "error_allowed",
                    "blocked": False,
                    "categories": [],
                    "message": "Naga moderation service unavailable; message sent without moderation block",
                    "model_name": "",
                }
                logger.warning(
                    "[NagaSend] 审核服务不可用，按允许发送: trace=%s naga_id=%s bind_uuid=%s",
                    trace_id,
                    naga_id,
                    bind_uuid,
                )
            else:
                logger.info(
                    "[NagaSend] 审核开始: trace=%s naga_id=%s bind_uuid=%s key=%s fmt=%s content_len=%s",
                    trace_id,
                    naga_id,
                    bind_uuid,
                    message_key,
                    message_format,
                    len(content),
                )
                result = await security.moderate_naga_message(
                    message_format=message_format,
                    content=content,
                )
                moderation = {
                    "status": result.status,
                    "blocked": result.blocked,
                    "categories": result.categories,
                    "message": result.message,
                    "model_name": result.model_name,
                }
                logger.info(
                    "[NagaSend] 审核完成: trace=%s naga_id=%s bind_uuid=%s key=%s blocked=%s status=%s model=%s categories=%s",
                    trace_id,
                    naga_id,
                    bind_uuid,
                    message_key,
                    result.blocked,
                    result.status,
                    result.model_name,
                    ",".join(result.categories) or "-",
                )
            if moderation["blocked"]:
                logger.warning(
                    "[NagaSend] 审核拦截: trace=%s naga_id=%s bind_uuid=%s key=%s reason=%s",
                    trace_id,
                    naga_id,
                    bind_uuid,
                    message_key,
                    moderation["message"],
                )
                return web.json_response(
                    {
                        "ok": False,
                        "error": "message blocked by moderation",
                        "moderation": moderation,
                    },
                    status=403,
                )

            send_content: str | None = content if message_format == "text" else None
            image_path: str | None = None
            tmp_path: str | None = None
            rendered = False
            render_fallback = False
            if message_format in {"markdown", "html"}:
                import tempfile

                try:
                    html_str = content
                    if message_format == "markdown":
                        html_str = await render_markdown_to_html(content)
                    fd, tmp_path = tempfile.mkstemp(suffix=".png", prefix="naga_send_")
                    os.close(fd)
                    await render_html_to_image(html_str, tmp_path)
                    image_path = tmp_path
                    rendered = True
                    logger.info(
                        "[NagaSend] 富文本渲染成功: trace=%s naga_id=%s bind_uuid=%s key=%s fmt=%s image=%s",
                        trace_id,
                        naga_id,
                        bind_uuid,
                        message_key,
                        message_format,
                        Path(tmp_path).name if tmp_path is not None else "",
                    )
                except Exception as exc:
                    logger.warning(
                        "[NagaSend] 渲染失败，回退文本发送: trace=%s naga_id=%s bind_uuid=%s key=%s err=%s",
                        trace_id,
                        naga_id,
                        bind_uuid,
                        message_key,
                        exc,
                    )
                    send_content = content
                    render_fallback = True

            sent_private = False
            sent_group = False
            group_policy_blocked = False

            async def _ensure_delivery_active() -> tuple[Any, Response | None]:
                current_binding, live_err = await naga_store.ensure_delivery_active(
                    naga_id=naga_id,
                    bind_uuid=bind_uuid,
                )
                if current_binding is None:
                    logger.warning(
                        "[NagaSend] 投递中止: trace=%s naga_id=%s bind_uuid=%s key=%s reason=%s",
                        trace_id,
                        naga_id,
                        bind_uuid,
                        message_key,
                        live_err.message
                        if live_err is not None
                        else "delivery no longer active",
                    )
                    return None, web.json_response(
                        {
                            "ok": False,
                            "error": (
                                live_err.message
                                if live_err is not None
                                else "delivery no longer active"
                            ),
                            "sent_private": sent_private,
                            "sent_group": sent_group,
                            "moderation": moderation,
                        },
                        status=live_err.http_status if live_err is not None else 409,
                    )
                return current_binding, None

            try:
                cq_image: str | None = None
                if image_path is not None:
                    file_uri = Path(image_path).resolve().as_uri()
                    cq_image = f"[CQ:image,file={file_uri}]"

                if mode in {"private", "both"}:
                    current_binding, abort_response = await _ensure_delivery_active()
                    if abort_response is not None:
                        return abort_response
                    logger.info(
                        "[NagaSend] 私聊投递开始: trace=%s naga_id=%s bind_uuid=%s key=%s qq=%s",
                        trace_id,
                        naga_id,
                        bind_uuid,
                        message_key,
                        current_binding.qq_id,
                    )
                    try:
                        if send_content is not None:
                            await sender.send_private_message(
                                current_binding.qq_id, send_content
                            )
                        elif cq_image is not None:
                            await sender.send_private_message(
                                current_binding.qq_id, cq_image
                            )
                        sent_private = True
                        logger.info(
                            "[NagaSend] 私聊投递成功: trace=%s naga_id=%s bind_uuid=%s key=%s qq=%s",
                            trace_id,
                            naga_id,
                            bind_uuid,
                            message_key,
                            current_binding.qq_id,
                        )
                    except Exception as exc:
                        logger.warning(
                            "[NagaSend] 私聊发送失败: trace=%s naga_id=%s qq=%d key=%s err=%s",
                            trace_id,
                            naga_id,
                            current_binding.qq_id,
                            message_key,
                            exc,
                        )

                if mode in {"group", "both"}:
                    current_binding, abort_response = await _ensure_delivery_active()
                    if abort_response is not None:
                        return abort_response
                    current_cfg = self._ctx.config_getter()
                    if current_binding.group_id not in current_cfg.naga.allowed_groups:
                        group_policy_blocked = True
                        logger.warning(
                            "[NagaSend] 群投递被策略阻止: trace=%s naga_id=%s bind_uuid=%s key=%s group=%s",
                            trace_id,
                            naga_id,
                            bind_uuid,
                            message_key,
                            current_binding.group_id,
                        )
                    else:
                        logger.info(
                            "[NagaSend] 群投递开始: trace=%s naga_id=%s bind_uuid=%s key=%s group=%s",
                            trace_id,
                            naga_id,
                            bind_uuid,
                            message_key,
                            current_binding.group_id,
                        )
                        try:
                            if send_content is not None:
                                await sender.send_group_message(
                                    current_binding.group_id, send_content
                                )
                            elif cq_image is not None:
                                await sender.send_group_message(
                                    current_binding.group_id, cq_image
                                )
                            sent_group = True
                            logger.info(
                                "[NagaSend] 群投递成功: trace=%s naga_id=%s bind_uuid=%s key=%s group=%s",
                                trace_id,
                                naga_id,
                                bind_uuid,
                                message_key,
                                current_binding.group_id,
                            )
                        except Exception as exc:
                            logger.warning(
                                "[NagaSend] 群聊发送失败: trace=%s naga_id=%s group=%d key=%s err=%s",
                                trace_id,
                                naga_id,
                                current_binding.group_id,
                                message_key,
                                exc,
                            )
            finally:
                if tmp_path is not None:
                    try:
                        os.unlink(tmp_path)
                    except OSError:
                        pass

            if mode == "private" and not sent_private:
                return web.json_response(
                    {
                        "ok": False,
                        "error": "private delivery failed",
                        "sent_private": sent_private,
                        "sent_group": sent_group,
                        "moderation": moderation,
                    },
                    status=502,
                )
            if mode == "group" and not sent_group:
                return web.json_response(
                    {
                        "ok": False,
                        "error": "group delivery failed",
                        "sent_private": sent_private,
                        "sent_group": sent_group,
                        "moderation": moderation,
                    },
                    status=502,
                )
            if mode == "both" and not (sent_private or sent_group):
                if group_policy_blocked:
                    return web.json_response(
                        {
                            "ok": False,
                            "error": "bound group is not in naga.allowed_groups",
                            "sent_private": sent_private,
                            "sent_group": sent_group,
                            "moderation": moderation,
                        },
                        status=403,
                    )
                return web.json_response(
                    {
                        "ok": False,
                        "error": "all deliveries failed",
                        "sent_private": sent_private,
                        "sent_group": sent_group,
                        "moderation": moderation,
                    },
                    status=502,
                )

            await naga_store.record_usage(naga_id, bind_uuid=bind_uuid)
            partial_success = mode == "both" and (sent_private != sent_group)
            logger.info(
                "[NagaSend] 请求完成: trace=%s naga_id=%s bind_uuid=%s key=%s sent_private=%s sent_group=%s partial=%s rendered=%s fallback=%s",
                trace_id,
                naga_id,
                bind_uuid,
                message_key,
                sent_private,
                sent_group,
                partial_success,
                rendered,
                render_fallback,
            )
            return web.json_response(
                {
                    "ok": True,
                    "naga_id": naga_id,
                    "bind_uuid": bind_uuid,
                    "sent_private": sent_private,
                    "sent_group": sent_group,
                    "partial_success": partial_success,
                    "delivery_status": (
                        "partial_success" if partial_success else "full_success"
                    ),
                    "rendered": rendered,
                    "render_fallback": render_fallback,
                    "moderation": moderation,
                }
            )
        finally:
            await naga_store.release_delivery(bind_uuid=bind_uuid)

    async def _naga_unbind_handler(self, request: web.Request) -> Response:
        """POST /api/v1/naga/unbind — 远端主动解绑。"""
        trace_id = _uuid.uuid4().hex[:8]
        auth_err = self._verify_naga_api_key(request)
        if auth_err is not None:
            logger.warning(
                "[NagaUnbind] 鉴权失败: trace=%s remote=%s err=%s",
                trace_id,
                getattr(request, "remote", None),
                auth_err,
            )
            return _json_error("Unauthorized", status=401)

        try:
            body = await request.json()
        except Exception:
            return _json_error("Invalid JSON", status=400)

        bind_uuid = str(body.get("bind_uuid", "") or "").strip()
        naga_id = str(body.get("naga_id", "") or "").strip()
        delivery_signature = str(body.get("delivery_signature", "") or "").strip()
        if not bind_uuid or not naga_id or not delivery_signature:
            return _json_error(
                "bind_uuid, naga_id and delivery_signature are required",
                status=400,
            )
        logger.info(
            "[NagaUnbind] 请求开始: trace=%s remote=%s naga_id=%s bind_uuid=%s signature=%s",
            trace_id,
            getattr(request, "remote", None),
            naga_id,
            bind_uuid,
            delivery_signature[:12] + "...",
        )

        naga_store = self._ctx.naga_store
        if naga_store is None:
            return _json_error("Naga integration not available", status=503)

        binding, changed, err = await naga_store.revoke_binding(
            naga_id,
            expected_bind_uuid=bind_uuid,
            delivery_signature=delivery_signature,
        )
        if binding is None:
            logger.warning(
                "[NagaUnbind] 吊销失败: trace=%s naga_id=%s bind_uuid=%s err=%s",
                trace_id,
                naga_id,
                bind_uuid,
                err.message if err is not None else "binding not found",
            )
            return _json_error(
                err.message if err is not None else "binding not found",
                status=err.http_status if err is not None else 404,
            )
        logger.info(
            "[NagaUnbind] 吊销完成: trace=%s naga_id=%s bind_uuid=%s changed=%s qq=%s group=%s",
            trace_id,
            naga_id,
            bind_uuid,
            changed,
            binding.qq_id,
            binding.group_id,
        )
        return web.json_response(
            {
                "ok": True,
                "idempotent": not changed,
                "naga_id": naga_id,
                "bind_uuid": bind_uuid,
            }
        )
