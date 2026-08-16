"""Automation workflow route handlers for the Runtime API."""

from __future__ import annotations

import uuid
from copy import deepcopy
from typing import Any

from aiohttp import web
from aiohttp.web_response import Response

from Undefined.api._context import RuntimeAPIContext
from Undefined.api._helpers import _json_error
from Undefined.api.routes.schedules import (
    SchedulePayloadError,
    _next_run_time_iso,
    _parse_existing_task_id,
    _parse_task_id,
    serialize_schedule_task,
)
from Undefined.automations.catalog import build_catalog
from Undefined.automations.constants import DEFAULT_MAX_NODES
from Undefined.automations.runner import find_start_node, start_kind
from Undefined.automations.short import build_short_automation, patch_nodes
from Undefined.automations.validate import (
    AutomationValidationError,
    collect_automation_issues,
)
from Undefined.utils.message_targets import parse_delivery_address


def _scheduler_unavailable() -> Response:
    return _json_error("Scheduler unavailable", status=503)


def serialize_automation(
    ctx: RuntimeAPIContext,
    task_id: str,
    task_info: dict[str, Any],
) -> dict[str, Any]:
    task = serialize_schedule_task(ctx, task_id, task_info)
    start = find_start_node(task_info)
    task["start_kind"] = start_kind(task_info)
    task["enabled"] = bool(task_info.get("enabled", True))
    task["consume_ai_loop"] = bool(task_info.get("consume_ai_loop", True))
    task["auto_send_final"] = bool(task_info.get("auto_send_final", True))
    task["last_status"] = task_info.get("last_status")
    task["last_run_at"] = task_info.get("last_run_at")
    task["last_error"] = task_info.get("last_error")
    task["last_node_id"] = task_info.get("last_node_id")
    task["nodes"] = deepcopy(task_info.get("nodes") or [])
    task["edges"] = deepcopy(task_info.get("edges") or [])
    ui = task_info.get("ui")
    if isinstance(ui, dict):
        task["ui"] = deepcopy(ui)
    elif "ui" in task:
        task.pop("ui", None)
    if isinstance(start, dict):
        task["channels"] = list(start.get("channels") or [])
        task["mentions"] = list(start.get("mentions") or [])
        task["text"] = start.get("text") or ""
        task["pass_text"] = start.get("pass_text") or ""
    task["next_run_time"] = _next_run_time_iso(ctx, task_id)
    return task


def _payload_task(body: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise SchedulePayloadError("Request body must be a JSON object")
    nested = body.get("task")
    if isinstance(nested, dict):
        merged = {
            **nested,
            **{key: value for key, value in body.items() if key != "task"},
        }
        return merged
    return body


async def _upsert(
    ctx: RuntimeAPIContext,
    task_id: str,
    body: dict[str, Any],
    *,
    merge_existing: bool,
) -> dict[str, Any]:
    scheduler = ctx.scheduler
    if scheduler is None:
        raise RuntimeError("unavailable")
    payload = _payload_task(body)
    existing = scheduler.list_tasks().get(task_id) if merge_existing else None
    if merge_existing and isinstance(existing, dict):
        merged = deepcopy(existing)
        skip = {"task_id", "patch_nodes", "merge"}
        for key, value in payload.items():
            if key in skip:
                continue
            if key in {"nodes", "edges"} and value is None:
                continue
            merged[key] = value
        if isinstance(payload.get("merge"), dict):
            merged.update(payload["merge"])
        patches = payload.get("patch_nodes")
        if isinstance(patches, list) and patches:
            merged = patch_nodes(merged, patches)
        if not isinstance(payload.get("nodes"), list):
            payload = merged
        else:
            payload = build_short_automation(merged)
    else:
        payload = build_short_automation(payload)
    if payload.get("address"):
        address, error = parse_delivery_address(payload.get("address"))
        if error or address is None:
            raise SchedulePayloadError(error or "address is invalid")
        payload["address"] = address.canonical
    upsert = getattr(scheduler, "upsert_automation", None)
    if not callable(upsert):
        raise SchedulePayloadError("Automation upsert is unavailable")
    await upsert(task_id, payload)
    stored = scheduler.list_tasks().get(task_id, payload)
    return serialize_automation(
        ctx, task_id, stored if isinstance(stored, dict) else payload
    )


def _max_nodes(ctx: RuntimeAPIContext) -> int:
    getter = getattr(ctx, "config_getter", None)
    if not callable(getter):
        return DEFAULT_MAX_NODES
    try:
        cfg = getter()
        automations_cfg = getattr(cfg, "automations", None)
        return int(
            getattr(automations_cfg, "max_nodes", DEFAULT_MAX_NODES)
            or DEFAULT_MAX_NODES
        )
    except Exception:
        return DEFAULT_MAX_NODES


async def automations_catalog_handler(
    ctx: RuntimeAPIContext, request: web.Request
) -> Response:
    _ = request
    bot_qq = None
    getter = getattr(ctx, "config_getter", None)
    if callable(getter):
        try:
            cfg = getter()
            bot_qq = int(getattr(cfg, "bot_qq", 0) or 0) or None
        except Exception:
            bot_qq = None
    return web.json_response(build_catalog(bot_qq=bot_qq, ai=getattr(ctx, "ai", None)))


async def automations_validate_handler(
    ctx: RuntimeAPIContext, request: web.Request
) -> Response:
    try:
        body = await request.json()
        if not isinstance(body, dict):
            raise SchedulePayloadError("Request body must be a JSON object")
        payload = build_short_automation(_payload_task(body))
    except SchedulePayloadError as exc:
        return _json_error(str(exc), status=400)
    except Exception:
        return _json_error("Invalid JSON", status=400)
    issues = collect_automation_issues(payload, max_nodes=_max_nodes(ctx))
    return web.json_response({"ok": not issues, "issues": issues})


async def automations_list_handler(
    ctx: RuntimeAPIContext, request: web.Request
) -> Response:
    _ = request
    scheduler = ctx.scheduler
    if scheduler is None:
        return _scheduler_unavailable()
    tasks = scheduler.list_tasks()
    items = [
        serialize_automation(ctx, task_id, task_info)
        for task_id, task_info in sorted(tasks.items())
        if isinstance(task_info, dict)
    ]
    return web.json_response({"count": len(items), "items": items})


async def automation_detail_handler(
    ctx: RuntimeAPIContext, request: web.Request
) -> Response:
    scheduler = ctx.scheduler
    if scheduler is None:
        return _scheduler_unavailable()
    try:
        task_id = _parse_existing_task_id(request.match_info.get("task_id", ""))
    except SchedulePayloadError as exc:
        return _json_error(str(exc), status=400)
    task_info = scheduler.list_tasks().get(task_id)
    if not isinstance(task_info, dict):
        return _json_error("Automation not found", status=404)
    return web.json_response({"task": serialize_automation(ctx, task_id, task_info)})


async def automations_create_handler(
    ctx: RuntimeAPIContext, request: web.Request
) -> Response:
    scheduler = ctx.scheduler
    if scheduler is None:
        return _scheduler_unavailable()
    try:
        body = await request.json()
        if not isinstance(body, dict):
            raise SchedulePayloadError("Request body must be a JSON object")
        raw_task_id = body.get("task_id")
        task_id = (
            _parse_task_id(raw_task_id)
            if raw_task_id
            else f"auto_{uuid.uuid4().hex[:12]}"
        )
    except SchedulePayloadError as exc:
        return _json_error(str(exc), status=400)
    except Exception:
        return _json_error("Invalid JSON", status=400)
    if task_id in scheduler.list_tasks():
        return _json_error("Automation already exists", status=409)
    try:
        task = await _upsert(ctx, task_id, body, merge_existing=False)
    except SchedulePayloadError as exc:
        return _json_error(str(exc), status=400)
    except AutomationValidationError as exc:
        return _json_error(str(exc), status=400)
    return web.json_response({"ok": True, "task": task}, status=201)


async def automation_update_handler(
    ctx: RuntimeAPIContext, request: web.Request
) -> Response:
    scheduler = ctx.scheduler
    if scheduler is None:
        return _scheduler_unavailable()
    try:
        task_id = _parse_existing_task_id(request.match_info.get("task_id", ""))
        body = await request.json()
        if task_id not in scheduler.list_tasks():
            return _json_error("Automation not found", status=404)
        if isinstance(body, dict) and "enabled" in body and len(body) == 1:
            set_enabled = getattr(scheduler, "set_enabled", None)
            if callable(set_enabled):
                await set_enabled(task_id, bool(body.get("enabled")))
                task_info = scheduler.list_tasks().get(task_id, {})
                return web.json_response(
                    {
                        "ok": True,
                        "task": serialize_automation(
                            ctx,
                            task_id,
                            task_info if isinstance(task_info, dict) else {},
                        ),
                    }
                )
        task = await _upsert(ctx, task_id, body, merge_existing=True)
    except SchedulePayloadError as exc:
        return _json_error(str(exc), status=400)
    except AutomationValidationError as exc:
        return _json_error(str(exc), status=400)
    except Exception:
        return _json_error("Invalid JSON", status=400)
    return web.json_response({"ok": True, "task": task})


async def automation_delete_handler(
    ctx: RuntimeAPIContext, request: web.Request
) -> Response:
    scheduler = ctx.scheduler
    if scheduler is None:
        return _scheduler_unavailable()
    try:
        task_id = _parse_existing_task_id(request.match_info.get("task_id", ""))
    except SchedulePayloadError as exc:
        return _json_error(str(exc), status=400)
    if task_id not in scheduler.list_tasks():
        return _json_error("Automation not found", status=404)
    success = await scheduler.remove_task(task_id)
    if not success:
        return _json_error("Failed to delete automation", status=400)
    return web.json_response({"ok": True, "task_id": task_id})
