from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

from Undefined.api import RuntimeAPIContext, RuntimeAPIServer
from Undefined.api.routes.schedules import (
    build_schedules_summary,
    serialize_schedule_task,
)
from Undefined.utils.scheduler import SELF_CALL_TOOL_NAME


class _FakeJob:
    def __init__(self) -> None:
        self.next_run_time = datetime(2026, 6, 7, 9, 0, tzinfo=timezone.utc)


class _FakeApscheduler:
    def __init__(self) -> None:
        self.running = True

    def get_job(self, _task_id: str) -> _FakeJob:
        return _FakeJob()


class _FakeScheduler:
    def __init__(self) -> None:
        self.scheduler = _FakeApscheduler()
        self.tasks: dict[str, dict[str, Any]] = {}

    def list_tasks(self) -> dict[str, dict[str, Any]]:
        return self.tasks


def _context(scheduler: Any) -> RuntimeAPIContext:
    return RuntimeAPIContext(
        config_getter=lambda: SimpleNamespace(
            api=SimpleNamespace(
                enabled=True,
                host="127.0.0.1",
                port=8788,
                openapi_enabled=True,
            )
        ),
        onebot=SimpleNamespace(connection_status=lambda: {}),
        ai=SimpleNamespace(memory_storage=None),
        command_dispatcher=SimpleNamespace(),
        queue_manager=SimpleNamespace(snapshot=lambda: {}),
        history_manager=SimpleNamespace(),
        scheduler=scheduler,
    )


def test_build_schedules_summary_includes_running_when_unavailable() -> None:
    assert build_schedules_summary(_context(None)) == {
        "available": False,
        "count": 0,
        "running": False,
    }


def test_build_schedules_summary_includes_running_when_list_tasks_missing() -> None:
    context = _context(SimpleNamespace(scheduler=SimpleNamespace(running=True)))

    assert build_schedules_summary(context) == {
        "available": False,
        "count": 0,
        "running": False,
    }


def test_serialize_schedule_task_includes_next_run_time() -> None:
    scheduler = _FakeScheduler()
    task = {
        "task_id": "task_daily",
        "task_name": "daily",
        "tool_name": "get_current_time",
        "tool_args": {},
        "cron": "0 9 * * *",
        "target_id": 10001,
        "target_type": "group",
    }
    item = serialize_schedule_task(_context(scheduler), "task_daily", task)
    assert item["task_id"] == "task_daily"
    assert item["mode"] == "single"
    assert item["next_run_time"] == "2026-06-07T09:00:00+00:00"
    assert item["address"] == "group:10001"


def test_serialize_schedule_task_preserves_single_item_multi_mode() -> None:
    scheduler = _FakeScheduler()
    task = {
        "task_id": "task_multi_one",
        "tools": [{"tool_name": "get_current_time", "tool_args": {}}],
        "execution_mode": "serial",
        "cron": "0 9 * * *",
    }
    item = serialize_schedule_task(_context(scheduler), "task_multi_one", task)
    assert item["mode"] == "multi"


def test_serialize_schedule_task_fills_self_instruction() -> None:
    scheduler = _FakeScheduler()
    task = {
        "task_id": "task_self",
        "tool_name": SELF_CALL_TOOL_NAME,
        "tool_args": {"prompt": "总结昨天群里的待办。"},
        "cron": "0 9 * * *",
    }
    item = serialize_schedule_task(_context(scheduler), "task_self", task)
    assert item["mode"] == "self_instruction"
    assert item["self_instruction"] == "总结昨天群里的待办。"


def test_runtime_api_does_not_expose_schedules_handlers() -> None:
    server = RuntimeAPIServer(_context(None), host="127.0.0.1", port=8788)
    assert not hasattr(server, "_schedules_list_handler")
    assert not hasattr(server, "_schedules_create_handler")
