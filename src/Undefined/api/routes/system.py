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
from Undefined.api.routes.schedules import build_schedules_summary

logger = logging.getLogger(__name__)

_PROCESS_START_TIME = time.time()


def _toolsets_summary(tool_registry: Any) -> dict[str, Any]:
    """从主工具注册表拆出 skills/toolsets 的独立摘要。"""
    if tool_registry is None:
        return {"count": 0, "loaded": 0, "categories": [], "items": []}

    items: dict[str, Any] = getattr(tool_registry, "_items", {})
    stats: dict[str, Any] = {}
    get_stats = getattr(tool_registry, "get_stats", None)
    if callable(get_stats):
        stats = get_stats()

    category_totals: dict[str, dict[str, int]] = {}
    summary_items: list[dict[str, Any]] = []
    for name, item in sorted(items.items()):
        if "." not in name:
            continue
        category = name.split(".", 1)[0]
        loaded = bool(getattr(item, "loaded", True))
        category_info = category_totals.setdefault(
            category,
            {"count": 0, "loaded": 0},
        )
        category_info["count"] += 1
        if loaded:
            category_info["loaded"] += 1

        st = stats.get(name)
        entry: dict[str, Any] = {
            "name": name,
            "category": category,
            "loaded": loaded,
        }
        if st is not None:
            entry["calls"] = getattr(st, "count", 0)
            entry["success"] = getattr(st, "success", 0)
            entry["failure"] = getattr(st, "failure", 0)
        summary_items.append(entry)

    categories = [
        {"name": name, **counts} for name, counts in sorted(category_totals.items())
    ]
    return {
        "count": len(summary_items),
        "loaded": sum(1 for item in summary_items if item["loaded"]),
        "categories": categories,
        "items": summary_items,
    }


async def _pipelines_summary(registry: Any) -> dict[str, Any]:
    """生成 skills/pipelines 的探针摘要。"""
    if registry is None:
        return {"count": 0, "loaded": 0, "items": [], "hot_reload": False}

    items: dict[str, Any]
    lock = getattr(registry, "_items_lock", None)
    if lock is not None:
        async with lock:
            items = dict(getattr(registry, "_items", {}))
    else:
        items = dict(getattr(registry, "_items", {}))

    summary_items = [
        {
            "name": name,
            "loaded": True,
            "order": getattr(item, "order", 0),
            "description": getattr(item, "description", ""),
        }
        for name, item in sorted(
            items.items(), key=lambda pair: (getattr(pair[1], "order", 0), pair[0])
        )
    ]
    return {
        "count": len(summary_items),
        "loaded": len(summary_items),
        "items": summary_items,
        "hot_reload": getattr(registry, "_watch_task", None) is not None,
    }


def _commands_summary(command_dispatcher: Any) -> dict[str, Any]:
    """生成 skills/commands 的探针摘要。"""
    command_registry = getattr(command_dispatcher, "command_registry", None)
    if command_registry is None:
        return {
            "count": 0,
            "loaded": 0,
            "aliases": 0,
            "subcommands": 0,
            "items": [],
        }

    list_commands = getattr(command_registry, "list_commands", None)
    if not callable(list_commands):
        return {
            "count": 0,
            "loaded": 0,
            "aliases": 0,
            "subcommands": 0,
            "items": [],
        }

    try:
        commands = list_commands(include_hidden=True)
    except TypeError:
        commands = list_commands()

    summary_items: list[dict[str, Any]] = []
    alias_count = 0
    subcommand_count = 0
    for command in commands:
        aliases = list(getattr(command, "aliases", []) or [])
        subcommands = getattr(command, "subcommands", {}) or {}
        alias_count += len(aliases)
        subcommand_count += len(subcommands)
        summary_items.append(
            {
                "name": getattr(command, "name", ""),
                "loaded": True,
                "handler_loaded": getattr(command, "handler", None) is not None,
                "aliases": aliases,
                "subcommands": len(subcommands),
                "permission": getattr(command, "permission", "public"),
                "allow_in_private": bool(getattr(command, "allow_in_private", False)),
                "show_in_help": bool(getattr(command, "show_in_help", True)),
            }
        )

    return {
        "count": len(summary_items),
        "loaded": len(summary_items),
        "aliases": alias_count,
        "subcommands": subcommand_count,
        "items": summary_items,
    }


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
    message_batcher_snapshot = (
        ctx.message_batcher.snapshot() if ctx.message_batcher else {}
    )
    memory_storage = getattr(ctx.ai, "memory_storage", None)
    memory_count = memory_storage.count() if memory_storage is not None else 0

    # Skills 统计
    ai = ctx.ai
    tool_reg = getattr(ai, "tool_registry", None) if ai is not None else None
    agent_reg = getattr(ai, "agent_registry", None) if ai is not None else None
    anthropic_reg = (
        getattr(ai, "anthropic_skill_registry", None) if ai is not None else None
    )
    skills_info: dict[str, Any] = {
        "tools": _registry_summary(tool_reg),
        "toolsets": _toolsets_summary(tool_reg),
        "agents": _registry_summary(agent_reg),
        "pipelines": await _pipelines_summary(ctx.pipeline_registry),
        "commands": _commands_summary(ctx.command_dispatcher),
        "anthropic_skills": _registry_summary(anthropic_reg),
    }

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
        "message_batcher": message_batcher_snapshot,
        "memory": {"count": memory_count, "virtual_user_id": _VIRTUAL_USER_ID},
        "cognitive": {
            "enabled": bool(ctx.cognitive_service and ctx.cognitive_service.enabled),
            "queue": cognitive_queue_snapshot,
        },
        "scheduler": build_schedules_summary(ctx),
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
