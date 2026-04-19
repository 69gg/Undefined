"""Runtime API server for Undefined.

Route handler logic lives in ``routes/`` sub-modules.  This file keeps only
the ``RuntimeAPIServer`` class (init / start / stop / middleware / routing)
and thin one-liner wrappers that delegate to the route functions so that
existing tests calling ``server._xxx_handler(request)`` keep working.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable

from aiohttp import web
from aiohttp.web_response import Response

from ._context import RuntimeAPIContext
from ._helpers import (
    _apply_cors_headers,
    _json_error,
    _naga_routes_enabled,
    _naga_runtime_enabled,
    _AUTH_HEADER,
)
from ._naga_state import NagaState
from .routes import chat, cognitive, health, memes, memory, naga, system, tools

logger = logging.getLogger(__name__)


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
        self._naga_state = NagaState()

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
                web.post("/api/v1/memory", self._memory_create_handler),
                web.patch("/api/v1/memory/{uuid}", self._memory_update_handler),
                web.delete("/api/v1/memory/{uuid}", self._memory_delete_handler),
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

    @property
    def _ctx(self) -> RuntimeAPIContext:
        return self._context

    # ------------------------------------------------------------------
    # Thin delegation wrappers — keep tests calling server._xxx(request)
    # ------------------------------------------------------------------

    # Health / System
    async def _health_handler(self, request: web.Request) -> Response:
        return await health.health_handler(self._ctx, request)

    async def _openapi_handler(self, request: web.Request) -> Response:
        return await system.openapi_handler(self._ctx, request)

    async def _internal_probe_handler(self, request: web.Request) -> Response:
        return await system.internal_probe_handler(self._ctx, request)

    async def _external_probe_handler(self, request: web.Request) -> Response:
        return await system.external_probe_handler(self._ctx, request)

    # Memory CRUD
    async def _memory_handler(self, request: web.Request) -> Response:
        return await memory.memory_list_handler(self._ctx, request)

    async def _memory_create_handler(self, request: web.Request) -> Response:
        return await memory.memory_create_handler(self._ctx, request)

    async def _memory_update_handler(self, request: web.Request) -> Response:
        return await memory.memory_update_handler(self._ctx, request)

    async def _memory_delete_handler(self, request: web.Request) -> Response:
        return await memory.memory_delete_handler(self._ctx, request)

    # Memes
    async def _meme_list_handler(self, request: web.Request) -> Response:
        return await memes.meme_list_handler(self._ctx, request)

    async def _meme_stats_handler(self, request: web.Request) -> Response:
        return await memes.meme_stats_handler(self._ctx, request)

    async def _meme_detail_handler(self, request: web.Request) -> Response:
        return await memes.meme_detail_handler(self._ctx, request)

    async def _meme_blob_handler(self, request: web.Request) -> Response:
        return await memes.meme_blob_handler(self._ctx, request)

    async def _meme_preview_handler(self, request: web.Request) -> Response:
        return await memes.meme_preview_handler(self._ctx, request)

    async def _meme_update_handler(self, request: web.Request) -> Response:
        return await memes.meme_update_handler(self._ctx, request)

    async def _meme_delete_handler(self, request: web.Request) -> Response:
        return await memes.meme_delete_handler(self._ctx, request)

    async def _meme_reanalyze_handler(self, request: web.Request) -> Response:
        return await memes.meme_reanalyze_handler(self._ctx, request)

    async def _meme_reindex_handler(self, request: web.Request) -> Response:
        return await memes.meme_reindex_handler(self._ctx, request)

    # Cognitive
    async def _cognitive_events_handler(self, request: web.Request) -> Response:
        return await cognitive.cognitive_events_handler(self._ctx, request)

    async def _cognitive_profiles_handler(self, request: web.Request) -> Response:
        return await cognitive.cognitive_profiles_handler(self._ctx, request)

    async def _cognitive_profile_handler(self, request: web.Request) -> Response:
        return await cognitive.cognitive_profile_handler(self._ctx, request)

    # Chat
    async def _run_webui_chat(
        self,
        *,
        text: str,
        send_output: Callable[[int, str], Awaitable[None]],
    ) -> str:
        return await chat.run_webui_chat(self._ctx, text=text, send_output=send_output)

    async def _chat_history_handler(self, request: web.Request) -> Response:
        return await chat.chat_history_handler(self._ctx, request)

    async def _chat_handler(self, request: web.Request) -> web.StreamResponse:
        return await chat.chat_handler(self._ctx, request)

    # Tools
    def _get_filtered_tools(self) -> list[dict[str, Any]]:
        return tools.get_filtered_tools(self._ctx)

    def _get_agent_tool_names(self) -> set[str]:
        return tools.get_agent_tool_names(self._ctx)

    async def _tools_list_handler(self, request: web.Request) -> Response:
        return await tools.tools_list_handler(self._ctx, request)

    async def _tools_invoke_handler(self, request: web.Request) -> Response:
        return await tools.tools_invoke_handler(
            self._ctx, self._background_tasks, request
        )

    async def _execute_tool_invoke(
        self,
        *,
        request_id: str,
        tool_name: str,
        args: dict[str, Any],
        body_context: Any,
        timeout: int,
    ) -> dict[str, Any]:
        return await tools.execute_tool_invoke(
            self._ctx,
            request_id=request_id,
            tool_name=tool_name,
            args=args,
            body_context=body_context,
            timeout=timeout,
        )

    # Naga
    def _verify_naga_api_key(self, request: web.Request) -> str | None:
        return naga.verify_naga_api_key(self._ctx, request)

    async def _naga_bind_callback_handler(self, request: web.Request) -> Response:
        return await naga.naga_bind_callback_handler(self._ctx, request)

    async def _naga_messages_send_handler(self, request: web.Request) -> Response:
        return await naga.naga_messages_send_handler(
            self._ctx, self._naga_state, request
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
        return await naga.naga_messages_send_impl(
            self._ctx,
            naga_id=naga_id,
            bind_uuid=bind_uuid,
            delivery_signature=delivery_signature,
            target_qq=target_qq,
            target_group=target_group,
            mode=mode,
            message_format=message_format,
            content=content,
            trace_id=trace_id,
            message_key=message_key,
        )

    async def _naga_unbind_handler(self, request: web.Request) -> Response:
        return await naga.naga_unbind_handler(self._ctx, request)
