"""Helpers for serializing automation tasks in Runtime API responses."""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

from Undefined.api._context import RuntimeAPIContext
from Undefined.automations.constants import SELF_CALL_TOOL_NAME
from Undefined.utils.message_targets import parse_delivery_address

_TASK_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,96}$")
_LEGACY_TASK_ID_MAX_LENGTH = 256
_MAX_TEXT_LENGTH = 16_000


class SchedulePayloadError(ValueError):
    """Raised when an automation API payload is invalid."""


def _clean_text(value: Any, *, field: str, max_length: int = _MAX_TEXT_LENGTH) -> str:
    text = str(value or "").strip()
    if len(text) > max_length:
        raise SchedulePayloadError(f"{field} is too long")
    return text


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


def _next_run_time_iso(ctx: RuntimeAPIContext, task_id: str) -> str | None:
    scheduler = ctx.scheduler
    next_run = getattr(scheduler, "next_run_iso", None)
    if not callable(next_run):
        return None
    value = next_run(task_id)
    if value is None:
        return None
    return str(value)


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
        "running": bool(getattr(scheduler, "clock_running", False)),
    }
