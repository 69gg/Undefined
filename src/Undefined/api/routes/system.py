"""System / probe route handlers for the Runtime API."""

from __future__ import annotations

import asyncio
import logging
import platform
import sys
import time
from datetime import datetime
from typing import Any

from aiohttp import web
from aiohttp.web_response import Response

from Undefined import __version__
from Undefined.api._context import RuntimeAPIContext
from Undefined.api._helpers import (
    _VIRTUAL_USER_ID,
    _json_error,
    _mask_url,
    _naga_routes_enabled,
    _registry_summary,
)
from Undefined.api._openapi import _build_openapi_spec
from Undefined.api._probes import (
    _build_internal_model_probe_payload,
    _probe_http_endpoint,
    _probe_ws_endpoint,
    _skipped_probe,
)

logger = logging.getLogger(__name__)

_PROCESS_START_TIME = time.time()


async def openapi_handler(ctx: RuntimeAPIContext, request: web.Request) -> Response:
    cfg = ctx.config_getter()
    if not bool(getattr(cfg.api, "openapi_enabled", True)):
        logger.info(
            "[RuntimeAPI] OpenAPI 请求被拒绝: disabled remote=%s", request.remote
        )
        return _json_error("OpenAPI disabled", status=404)
    naga_routes_enabled = _naga_routes_enabled(cfg, ctx.naga_store)
    logger.info(
        "[RuntimeAPI] OpenAPI 请求: remote=%s naga_routes_enabled=%s",
        request.remote,
        naga_routes_enabled,
    )
    return web.json_response(_build_openapi_spec(ctx, request))


async def internal_probe_handler(
    ctx: RuntimeAPIContext, request: web.Request
) -> Response:
    _ = request
    cfg = ctx.config_getter()
    queue_snapshot = ctx.queue_manager.snapshot() if ctx.queue_manager else {}
    cognitive_queue_snapshot = (
        ctx.cognitive_job_queue.snapshot() if ctx.cognitive_job_queue else {}
    )
    memory_storage = getattr(ctx.ai, "memory_storage", None)
    memory_count = memory_storage.count() if memory_storage is not None else 0

    # Skills 统计
    ai = ctx.ai
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
        "onebot": ctx.onebot.connection_status() if ctx.onebot is not None else {},
        "queues": queue_snapshot,
        "memory": {"count": memory_count, "virtual_user_id": _VIRTUAL_USER_ID},
        "cognitive": {
            "enabled": bool(ctx.cognitive_service and ctx.cognitive_service.enabled),
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


async def external_probe_handler(
    ctx: RuntimeAPIContext, request: web.Request
) -> Response:
    _ = request
    cfg = ctx.config_getter()
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
