from __future__ import annotations

import asyncio
import json
import logging
import platform
import socket
import sys
import time
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Awaitable, Callable
from urllib.parse import urlsplit

from aiohttp import ClientSession, ClientTimeout, web
from aiohttp.web_response import Response

from Undefined import __version__
from Undefined.context import RequestContext
from Undefined.utils.recent_messages import get_recent_messages_prefer_local
from Undefined.utils.xml import escape_xml_attr, escape_xml_text

logger = logging.getLogger(__name__)

_VIRTUAL_USER_ID = 42
_VIRTUAL_USER_NAME = "system"
_AUTH_HEADER = "X-Undefined-API-Key"
_CHAT_SSE_KEEPALIVE_SECONDS = 10.0
_PROCESS_START_TIME = time.time()


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
    ) -> None:
        _ = user_id, auto_history, mark_sent
        await self._send_private_callback(self._virtual_user_id, message)

    async def send_group_message(
        self,
        group_id: int,
        message: str,
        auto_history: bool = True,
        history_prefix: str = "",
        *,
        mark_sent: bool = True,
    ) -> None:
        _ = group_id, auto_history, history_prefix, mark_sent
        await self._send_private_callback(self._virtual_user_id, message)

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


def _json_error(message: str, status: int = 400) -> Response:
    return web.json_response({"error": message}, status=status)


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


def _build_openapi_spec(ctx: RuntimeAPIContext) -> dict[str, Any]:
    cfg = ctx.config_getter()
    return {
        "openapi": "3.0.3",
        "info": {
            "title": "Undefined Runtime API",
            "version": __version__,
            "description": "API exposed by the main Undefined process.",
        },
        "servers": [
            {
                "url": f"http://{cfg.api.host}:{cfg.api.port}",
                "description": "Local runtime endpoint",
            }
        ],
        "components": {
            "securitySchemes": {
                "ApiKeyAuth": {
                    "type": "apiKey",
                    "in": "header",
                    "name": _AUTH_HEADER,
                }
            }
        },
        "security": [{"ApiKeyAuth": []}],
        "paths": {
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
                        "(chat, vision, security, agent, embedding, rerank) "
                        "and OneBot WebSocket. Each result includes status, "
                        "model name, masked URL, HTTP status code, and latency."
                    ),
                }
            },
            "/api/v1/memory": {"get": {"summary": "List/search manual memories"}},
            "/api/v1/cognitive/events": {
                "get": {"summary": "Search cognitive event memories"}
            },
            "/api/v1/cognitive/profiles": {
                "get": {"summary": "Search cognitive profiles"}
            },
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
        },
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
        self._site: web.TCPSite | None = None

    async def start(self) -> None:
        app = self._create_app()
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, host=self._host, port=self._port)
        await self._site.start()
        logger.info(
            "[RuntimeAPI] 已启动: http://%s:%s",
            self._host,
            self._port,
        )

    async def stop(self) -> None:
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
            if request.path.startswith("/api/"):
                expected = str(self._context.config_getter().api.auth_key or "")
                provided = request.headers.get(_AUTH_HEADER, "")
                if not expected or provided != expected:
                    return _json_error("Unauthorized", status=401)
            return await handler(request)

        app = web.Application(middlewares=[_auth_middleware])
        app["runtime_api_context"] = self._context
        app.add_routes(
            [
                web.get("/health", self._health_handler),
                web.get("/openapi.json", self._openapi_handler),
                web.get("/api/v1/probes/internal", self._internal_probe_handler),
                web.get("/api/v1/probes/external", self._external_probe_handler),
                web.get("/api/v1/memory", self._memory_handler),
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
            ]
        )
        return app

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
        _ = request
        cfg = self._ctx.config_getter()
        if not bool(getattr(cfg.api, "openapi_enabled", True)):
            return _json_error("OpenAPI disabled", status=404)
        return web.json_response(_build_openapi_spec(self._ctx))

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
        for label in ("chat_model", "vision_model", "agent_model", "security_model"):
            mcfg = getattr(cfg, label, None)
            if mcfg is not None:
                models_info[label] = {
                    "model_name": getattr(mcfg, "model_name", ""),
                    "api_url": _mask_url(getattr(mcfg, "api_url", "")),
                    "thinking_enabled": getattr(mcfg, "thinking_enabled", False),
                }
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
            _probe_http_endpoint(
                name="agent_model",
                base_url=cfg.agent_model.api_url,
                api_key=cfg.agent_model.api_key,
                model_name=cfg.agent_model.model_name,
            ),
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
        await self._ctx.history_manager.add_private_message(
            user_id=_VIRTUAL_USER_ID,
            text_content=text,
            display_name=_VIRTUAL_USER_NAME,
            user_name=_VIRTUAL_USER_NAME,
        )

        command = self._ctx.command_dispatcher.parse_command(text)
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
        full_question = f"""<message sender="{escape_xml_attr(_VIRTUAL_USER_NAME)}" sender_id="{escape_xml_attr(_VIRTUAL_USER_ID)}" location="WebUI私聊" time="{escape_xml_attr(current_time)}">
 <content>{escape_xml_text(text)}</content>
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
            )

        async with RequestContext(
            request_type="private",
            user_id=_VIRTUAL_USER_ID,
            sender_id=permission_sender_id,
        ):
            result = await self._ctx.ai.ask(
                full_question,
                send_message_callback=lambda msg: send_output(_VIRTUAL_USER_ID, msg),
                get_recent_messages_callback=_get_recent_cb,
                get_image_url_callback=self._ctx.onebot.get_image,
                get_forward_msg_callback=self._ctx.onebot.get_forward_msg,
                sender=virtual_sender,
                history_manager=self._ctx.history_manager,
                onebot_client=self._ctx.onebot,
                scheduler=self._ctx.scheduler,
                extra_context={
                    "is_private_chat": True,
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

        async def _capture_private_message(user_id: int, message: str) -> None:
            _ = user_id
            content = str(message or "").strip()
            if not content:
                return
            outputs.append(content)
            await self._ctx.history_manager.add_private_message(
                user_id=_VIRTUAL_USER_ID,
                text_content=content,
                display_name="Bot",
                user_name="Bot",
            )

        if not stream:
            mode = await self._run_webui_chat(
                text=text, send_output=_capture_private_message
            )
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
            await _capture_private_message(user_id, message)
            content = str(message or "").strip()
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
