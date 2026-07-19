"""Scheduled task route handlers for the Runtime API."""

from __future__ import annotations

import re
import uuid
from copy import deepcopy
from typing import Any

from aiohttp import web
from aiohttp.web_response import Response
from apscheduler.triggers.cron import CronTrigger

from Undefined.api._context import RuntimeAPIContext
from Undefined.api._helpers import _json_error
from Undefined.utils.message_targets import parse_delivery_address
from Undefined.utils.scheduler import SELF_CALL_TOOL_NAME

_TASK_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,96}$")
_LEGACY_TASK_ID_MAX_LENGTH = 256
_MAX_TEXT_LENGTH = 16_000
_MAX_TOOLS = 20
_TARGET_TYPES = frozenset({"group", "private"})
_EXECUTION_MODES = frozenset({"serial", "parallel"})
_TASK_MODES = frozenset({"single", "multi", "self_instruction"})


class SchedulePayloadError(ValueError):
    """Raised when a schedule API payload is invalid."""


def _scheduler_unavailable() -> Response:
    return _json_error("Scheduler unavailable", status=503)


def _clean_text(value: Any, *, field: str, max_length: int = _MAX_TEXT_LENGTH) -> str:
    text = str(value or "").strip()
    if len(text) > max_length:
        raise SchedulePayloadError(f"{field} is too long")
    return text


def _optional_text(
    body: dict[str, Any],
    field: str,
    *,
    max_length: int = _MAX_TEXT_LENGTH,
) -> str | None:
    if field not in body:
        return None
    return _clean_text(body.get(field), field=field, max_length=max_length)


def _parse_task_id(value: Any) -> str:
    task_id = _clean_text(value, field="task_id", max_length=96)
    if not task_id or _TASK_ID_RE.fullmatch(task_id) is None:
        raise SchedulePayloadError("task_id contains unsupported characters")
    return task_id


def _parse_existing_task_id(value: Any) -> str:
    task_id = _clean_text(
        value,
        field="task_id",
        max_length=_LEGACY_TASK_ID_MAX_LENGTH,
    )
    if not task_id:
        raise SchedulePayloadError("task_id is required")
    return task_id


def _parse_json_object(
    value: Any, *, field: str, default: dict[str, Any]
) -> dict[str, Any]:
    if value is None:
        return dict(default)
    if not isinstance(value, dict):
        raise SchedulePayloadError(f"{field} must be a JSON object")
    return deepcopy(value)


def _parse_optional_positive_int(
    value: Any,
    *,
    field: str,
    allow_null: bool = True,
) -> int | None:
    if value is None or value == "":
        if allow_null:
            return None
        raise SchedulePayloadError(f"{field} is required")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise SchedulePayloadError(f"{field} must be a positive integer") from exc
    if parsed < 1:
        raise SchedulePayloadError(f"{field} must be a positive integer")
    return parsed


def _parse_target_type(value: Any) -> str:
    target_type = _clean_text(value or "group", field="target_type", max_length=16)
    if target_type not in _TARGET_TYPES:
        raise SchedulePayloadError("target_type must be 'group' or 'private'")
    return target_type


def _parse_address(value: Any) -> str | None:
    if value is None or str(value).strip() == "":
        return None
    address, error = parse_delivery_address(value)
    if error or address is None:
        raise SchedulePayloadError(error or "address is invalid")
    return address.canonical


def _parse_execution_mode(value: Any) -> str:
    execution_mode = _clean_text(
        value or "serial", field="execution_mode", max_length=16
    )
    if execution_mode not in _EXECUTION_MODES:
        raise SchedulePayloadError("execution_mode must be 'serial' or 'parallel'")
    return execution_mode


def _parse_cron_expression(body: dict[str, Any], *, required: bool) -> str | None:
    raw = body.get("cron_expression", body.get("cron"))
    cron_expression = _clean_text(raw, field="cron_expression", max_length=128)
    if not cron_expression:
        if required:
            raise SchedulePayloadError("cron_expression is required")
        return None
    try:
        CronTrigger.from_crontab(cron_expression)
    except Exception as exc:
        raise SchedulePayloadError("cron_expression is invalid") from exc
    return cron_expression


def _parse_tools(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise SchedulePayloadError("tools must be a non-empty array")
    if len(value) > _MAX_TOOLS:
        raise SchedulePayloadError(f"tools can contain at most {_MAX_TOOLS} items")

    tools: list[dict[str, Any]] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise SchedulePayloadError(f"tools[{index}] must be a JSON object")
        tool_name = _clean_text(
            item.get("tool_name"),
            field=f"tools[{index}].tool_name",
            max_length=160,
        )
        if not tool_name:
            raise SchedulePayloadError(f"tools[{index}].tool_name is required")
        tool_args = _parse_json_object(
            item.get("tool_args", {}),
            field=f"tools[{index}].tool_args",
            default={},
        )
        tools.append({"tool_name": tool_name, "tool_args": tool_args})
    return tools


def _resolve_mode(body: dict[str, Any], *, required: bool) -> str | None:
    raw_mode = body.get("mode")
    mode = _clean_text(raw_mode, field="mode", max_length=32)
    aliases = {
        "self": "self_instruction",
        "self_instruction": "self_instruction",
        "single": "single",
        "tool": "single",
        "multi": "multi",
        "tools": "multi",
    }
    if mode:
        resolved = aliases.get(mode)
        if resolved is None or resolved not in _TASK_MODES:
            raise SchedulePayloadError(
                "mode must be 'single', 'multi', or 'self_instruction'"
            )
        return resolved

    flags = [
        ("single", body.get("tool_name") is not None),
        ("multi", body.get("tools") is not None),
        ("self_instruction", body.get("self_instruction") is not None),
    ]
    present = [name for name, enabled in flags if enabled]
    if len(present) > 1:
        raise SchedulePayloadError(
            "tool_name, tools, and self_instruction are mutually exclusive"
        )
    if present:
        return present[0]
    if required:
        raise SchedulePayloadError("mode or task content is required")
    return None


def _normalize_schedule_payload(
    body: dict[str, Any],
    *,
    partial: bool,
) -> tuple[dict[str, Any], set[str]]:
    if not isinstance(body, dict):
        raise SchedulePayloadError("Request body must be a JSON object")

    normalized: dict[str, Any] = {}
    provided: set[str] = set()

    cron_expression = _parse_cron_expression(body, required=not partial)
    if cron_expression is not None:
        normalized["cron_expression"] = cron_expression
        provided.add("cron_expression")

    task_name = _optional_text(body, "task_name", max_length=128)
    if task_name is not None:
        normalized["task_name"] = task_name
        provided.add("task_name")

    if "address" in body:
        normalized["address"] = _parse_address(body.get("address"))
        provided.add("address")

    if "target_type" in body:
        normalized["target_type"] = _parse_target_type(body.get("target_type"))
        provided.add("target_type")
    elif not partial and "address" not in body:
        normalized["target_type"] = "group"
        provided.add("target_type")

    if "target_id" in body:
        normalized["target_id"] = _parse_optional_positive_int(
            body.get("target_id"),
            field="target_id",
        )
        provided.add("target_id")

    if (
        normalized.get("address") is not None
        and normalized.get("target_id") is not None
    ):
        legacy_channel = (
            "group" if normalized.get("target_type", "group") == "group" else "qq"
        )
        legacy_address = f"{legacy_channel}:{normalized['target_id']}"
        if legacy_address != normalized["address"]:
            raise SchedulePayloadError(
                "address conflicts with target_type and target_id"
            )

    if "max_executions" in body:
        normalized["max_executions"] = _parse_optional_positive_int(
            body.get("max_executions"),
            field="max_executions",
        )
        provided.add("max_executions")

    mode = _resolve_mode(body, required=not partial)
    if mode is not None:
        mode_fields = {
            "tool_name": "single",
            "tools": "multi",
            "self_instruction": "self_instruction",
        }
        conflicts = [
            field
            for field, field_mode in mode_fields.items()
            if field in body and field_mode != mode
        ]
        if conflicts:
            raise SchedulePayloadError(
                "mode conflicts with fields: " + ", ".join(sorted(conflicts))
            )
        normalized["mode"] = mode
        provided.add("mode")
        if mode == "self_instruction":
            instruction = _clean_text(
                body.get("self_instruction"), field="self_instruction"
            )
            if not instruction:
                raise SchedulePayloadError("self_instruction is required")
            normalized["tool_name"] = SELF_CALL_TOOL_NAME
            normalized["tool_args"] = {"prompt": instruction}
            normalized["self_instruction"] = instruction
            normalized["tools"] = None
            normalized["execution_mode"] = "serial"
        elif mode == "single":
            tool_name = _clean_text(
                body.get("tool_name"), field="tool_name", max_length=160
            )
            if not tool_name:
                raise SchedulePayloadError("tool_name is required")
            normalized["tool_name"] = tool_name
            normalized["tool_args"] = _parse_json_object(
                body.get("tool_args", {}),
                field="tool_args",
                default={},
            )
            normalized["tools"] = None
            if "execution_mode" in body:
                normalized["execution_mode"] = _parse_execution_mode(
                    body.get("execution_mode")
                )
                provided.add("execution_mode")
        else:
            tools = _parse_tools(body.get("tools"))
            normalized["tools"] = tools
            normalized["tool_name"] = tools[0]["tool_name"]
            normalized["tool_args"] = tools[0]["tool_args"]
            normalized["execution_mode"] = _parse_execution_mode(
                body.get("execution_mode")
            )
            normalized["self_instruction"] = None
    elif "execution_mode" in body:
        normalized["execution_mode"] = _parse_execution_mode(body.get("execution_mode"))
        provided.add("execution_mode")

    if mode is None and "tool_args" in body:
        normalized["tool_args"] = _parse_json_object(
            body.get("tool_args", {}),
            field="tool_args",
            default={},
        )
        provided.add("tool_args")

    return normalized, provided


def _next_run_time_iso(ctx: RuntimeAPIContext, task_id: str) -> str | None:
    scheduler = ctx.scheduler
    apscheduler = getattr(scheduler, "scheduler", None)
    get_job = getattr(apscheduler, "get_job", None)
    if not callable(get_job):
        return None
    job = get_job(task_id)
    next_run_time = getattr(job, "next_run_time", None) if job is not None else None
    if next_run_time is None:
        return None
    return str(next_run_time.isoformat())


def _schedule_task_mode(task: dict[str, Any]) -> str:
    tools = task.get("tools")
    if isinstance(tools, list) and tools:
        if len(tools) == 1 and tools[0].get("tool_name") == SELF_CALL_TOOL_NAME:
            return "self_instruction"
        return "multi"
    if task.get("self_instruction") or task.get("tool_name") == SELF_CALL_TOOL_NAME:
        return "self_instruction"
    return "single"


def serialize_schedule_task(
    ctx: RuntimeAPIContext,
    task_id: str,
    task_info: dict[str, Any],
) -> dict[str, Any]:
    task = deepcopy(task_info)
    task.setdefault("task_id", task_id)
    task["mode"] = _schedule_task_mode(task)
    task["next_run_time"] = _next_run_time_iso(ctx, task_id)
    address, _error = parse_delivery_address(task.get("address"))
    if address is None and task.get("target_id") is not None:
        channel = "group" if task.get("target_type") == "group" else "qq"
        address, _error = parse_delivery_address(f"{channel}:{task['target_id']}")
    task["address"] = address.canonical if address is not None else None
    tool_args = task.get("tool_args")
    tools = task.get("tools")
    if (
        not task.get("self_instruction")
        and isinstance(tools, list)
        and len(tools) == 1
        and isinstance(tools[0], dict)
        and tools[0].get("tool_name") == SELF_CALL_TOOL_NAME
        and isinstance(tools[0].get("tool_args"), dict)
    ):
        prompt = str(tools[0]["tool_args"].get("prompt", "")).strip()
        if prompt:
            task["self_instruction"] = prompt
    if (
        task.get("tool_name") == SELF_CALL_TOOL_NAME
        and not task.get("self_instruction")
        and isinstance(tool_args, dict)
    ):
        prompt = str(tool_args.get("prompt", "")).strip()
        if prompt:
            task["self_instruction"] = prompt
    return task


def build_schedules_summary(ctx: RuntimeAPIContext) -> dict[str, Any]:
    scheduler = ctx.scheduler
    if scheduler is None:
        return {"available": False, "count": 0, "running": False}
    list_tasks = getattr(scheduler, "list_tasks", None)
    if not callable(list_tasks):
        return {"available": False, "count": 0, "running": False}
    tasks = list_tasks()
    return {
        "available": True,
        "count": len(tasks),
        "running": bool(
            getattr(getattr(scheduler, "scheduler", None), "running", False)
        ),
    }


async def schedules_list_handler(
    ctx: RuntimeAPIContext, request: web.Request
) -> Response:
    _ = request
    scheduler = ctx.scheduler
    if scheduler is None:
        return _scheduler_unavailable()
    tasks = scheduler.list_tasks()
    items = [
        serialize_schedule_task(ctx, task_id, task_info)
        for task_id, task_info in sorted(tasks.items())
        if isinstance(task_info, dict)
    ]
    return web.json_response({"count": len(items), "items": items})


async def schedule_detail_handler(
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
        return _json_error("Schedule task not found", status=404)
    return web.json_response({"task": serialize_schedule_task(ctx, task_id, task_info)})


async def schedules_create_handler(
    ctx: RuntimeAPIContext, request: web.Request
) -> Response:
    scheduler = ctx.scheduler
    if scheduler is None:
        return _scheduler_unavailable()
    try:
        body = await request.json()
        normalized, _provided = _normalize_schedule_payload(body, partial=False)
        raw_task_id = body.get("task_id") if isinstance(body, dict) else None
        if (
            isinstance(body, dict)
            and "task_id" in body
            and not _clean_text(
                raw_task_id,
                field="task_id",
                max_length=96,
            )
        ):
            raise SchedulePayloadError("task_id is required")
        task_id = (
            _parse_task_id(raw_task_id)
            if raw_task_id
            else f"task_{uuid.uuid4().hex[:12]}"
        )
    except SchedulePayloadError as exc:
        return _json_error(str(exc), status=400)
    except Exception:
        return _json_error("Invalid JSON", status=400)

    if task_id in scheduler.list_tasks():
        return _json_error("Schedule task already exists", status=409)

    success = await scheduler.add_task(
        task_id=task_id,
        tool_name=str(normalized["tool_name"]),
        tool_args=normalized["tool_args"],
        cron_expression=str(normalized["cron_expression"]),
        target_id=normalized.get("target_id"),
        target_type=str(normalized.get("target_type") or "group"),
        target_address=normalized.get("address"),
        task_name=normalized.get("task_name"),
        max_executions=normalized.get("max_executions"),
        tools=normalized.get("tools"),
        execution_mode=str(normalized.get("execution_mode") or "serial"),
        self_instruction=normalized.get("self_instruction"),
    )
    if not success:
        return _json_error("Failed to create schedule task", status=400)
    task_info = scheduler.list_tasks().get(task_id, {})
    return web.json_response(
        {"ok": True, "task": serialize_schedule_task(ctx, task_id, task_info)},
        status=201,
    )


async def schedule_update_handler(
    ctx: RuntimeAPIContext, request: web.Request
) -> Response:
    scheduler = ctx.scheduler
    if scheduler is None:
        return _scheduler_unavailable()
    try:
        task_id = _parse_existing_task_id(request.match_info.get("task_id", ""))
        body = await request.json()
        normalized, provided = _normalize_schedule_payload(body, partial=True)
    except SchedulePayloadError as exc:
        return _json_error(str(exc), status=400)
    except Exception:
        return _json_error("Invalid JSON", status=400)

    if task_id not in scheduler.list_tasks():
        return _json_error("Schedule task not found", status=404)

    if not normalized and not provided:
        return _json_error("No schedule fields provided", status=400)

    kwargs: dict[str, Any] = {
        "task_id": task_id,
        "cron_expression": normalized.get("cron_expression"),
        "tool_name": normalized.get("tool_name"),
        "tool_args": normalized.get("tool_args"),
        "task_name": normalized.get("task_name") if "task_name" in provided else None,
        "tools": normalized.get("tools") if "mode" in provided else None,
        "execution_mode": normalized.get("execution_mode"),
        "self_instruction": normalized.get("self_instruction"),
    }
    if "target_id" in provided:
        kwargs["target_id"] = normalized.get("target_id")
        kwargs["target_id_provided"] = True
    if "target_type" in provided:
        kwargs["target_type"] = normalized.get("target_type")
    if "address" in provided:
        kwargs["target_address"] = normalized.get("address")
        kwargs["target_address_provided"] = True
    if "max_executions" in provided:
        kwargs["max_executions"] = normalized.get("max_executions")
        kwargs["max_executions_provided"] = True

    success = await scheduler.update_task(**kwargs)
    if not success:
        return _json_error("Failed to update schedule task", status=400)
    task_info = scheduler.list_tasks().get(task_id, {})
    return web.json_response(
        {"ok": True, "task": serialize_schedule_task(ctx, task_id, task_info)}
    )


async def schedule_delete_handler(
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
        return _json_error("Schedule task not found", status=404)
    success = await scheduler.remove_task(task_id)
    if not success:
        return _json_error("Failed to delete schedule task", status=400)
    return web.json_response({"ok": True, "task_id": task_id})
