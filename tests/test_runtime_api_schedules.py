from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, cast

import pytest
from aiohttp import web

from Undefined.api import RuntimeAPIContext, RuntimeAPIServer
from Undefined.utils.scheduler import SELF_CALL_TOOL_NAME


class _JsonRequest(SimpleNamespace):
    async def json(self) -> dict[str, Any]:
        return dict(getattr(self, "_json", {}))


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
        self.add_calls: list[dict[str, Any]] = []
        self.update_calls: list[dict[str, Any]] = []
        self.remove_calls: list[str] = []

    def list_tasks(self) -> dict[str, dict[str, Any]]:
        return self.tasks

    async def add_task(self, **kwargs: Any) -> bool:
        self.add_calls.append(dict(kwargs))
        task_id = str(kwargs["task_id"])
        self.tasks[task_id] = {
            "task_id": task_id,
            "task_name": kwargs.get("task_name") or "",
            "tool_name": kwargs["tool_name"],
            "tool_args": kwargs["tool_args"],
            "cron": kwargs["cron_expression"],
            "target_id": kwargs.get("target_id"),
            "target_type": kwargs.get("target_type"),
            "max_executions": kwargs.get("max_executions"),
            "tools": kwargs.get("tools"),
            "execution_mode": kwargs.get("execution_mode"),
            "self_instruction": kwargs.get("self_instruction"),
        }
        return True

    async def update_task(self, **kwargs: Any) -> bool:
        self.update_calls.append(dict(kwargs))
        task_id = str(kwargs["task_id"])
        task = self.tasks[task_id]
        if kwargs.get("cron_expression") is not None:
            task["cron"] = kwargs["cron_expression"]
        if kwargs.get("target_id_provided"):
            task["target_id"] = kwargs.get("target_id")
        if kwargs.get("target_type") is not None:
            task["target_type"] = kwargs.get("target_type")
        if kwargs.get("max_executions_provided"):
            task["max_executions"] = kwargs.get("max_executions")
        if kwargs.get("tool_name") is not None:
            task["tool_name"] = kwargs.get("tool_name")
            task["tool_args"] = kwargs.get("tool_args", {})
        return True

    async def remove_task(self, task_id: str) -> bool:
        self.remove_calls.append(task_id)
        self.tasks.pop(task_id, None)
        return True


def _context(scheduler: _FakeScheduler) -> RuntimeAPIContext:
    return RuntimeAPIContext(
        config_getter=lambda: SimpleNamespace(
            api=SimpleNamespace(
                enabled=True,
                host="127.0.0.1",
                port=8788,
                auth_key="changeme",
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


def _payload(response: web.Response) -> dict[str, Any]:
    assert response.text is not None
    return cast(dict[str, Any], json.loads(response.text))


@pytest.mark.asyncio
async def test_runtime_schedule_list_returns_items_with_next_run_time() -> None:
    scheduler = _FakeScheduler()
    scheduler.tasks["task_daily"] = {
        "task_id": "task_daily",
        "task_name": "daily",
        "tool_name": "get_current_time",
        "tool_args": {},
        "cron": "0 9 * * *",
        "target_id": 10001,
        "target_type": "group",
    }
    server = RuntimeAPIServer(_context(scheduler), host="127.0.0.1", port=8788)

    response = await server._schedules_list_handler(
        cast(web.Request, cast(Any, SimpleNamespace()))
    )
    payload = _payload(response)

    assert payload["count"] == 1
    item = cast(list[dict[str, Any]], payload["items"])[0]
    assert item["task_id"] == "task_daily"
    assert item["mode"] == "single"
    assert item["next_run_time"] == "2026-06-07T09:00:00+00:00"


@pytest.mark.asyncio
async def test_runtime_schedule_list_preserves_single_item_multi_mode() -> None:
    scheduler = _FakeScheduler()
    scheduler.tasks["task_multi_one"] = {
        "task_id": "task_multi_one",
        "task_name": "single item multi",
        "tool_name": "get_current_time",
        "tool_args": {},
        "tools": [{"tool_name": "get_current_time", "tool_args": {}}],
        "execution_mode": "serial",
        "cron": "0 9 * * *",
        "target_id": None,
        "target_type": "group",
    }
    server = RuntimeAPIServer(_context(scheduler), host="127.0.0.1", port=8788)

    response = await server._schedules_list_handler(
        cast(web.Request, cast(Any, SimpleNamespace()))
    )
    payload = _payload(response)

    item = cast(list[dict[str, Any]], payload["items"])[0]
    assert item["mode"] == "multi"
    assert item["tools"] == [{"tool_name": "get_current_time", "tool_args": {}}]


@pytest.mark.asyncio
async def test_runtime_schedule_list_marks_single_self_tool_as_self_instruction() -> (
    None
):
    scheduler = _FakeScheduler()
    scheduler.tasks["task_self_tool"] = {
        "task_id": "task_self_tool",
        "task_name": "single self tool",
        "tool_name": SELF_CALL_TOOL_NAME,
        "tool_args": {"prompt": "请检查提醒事项。"},
        "tools": [
            {
                "tool_name": SELF_CALL_TOOL_NAME,
                "tool_args": {"prompt": "请检查提醒事项。"},
            }
        ],
        "execution_mode": "serial",
        "cron": "0 9 * * *",
        "target_id": None,
        "target_type": "group",
    }
    server = RuntimeAPIServer(_context(scheduler), host="127.0.0.1", port=8788)

    response = await server._schedules_list_handler(
        cast(web.Request, cast(Any, SimpleNamespace()))
    )
    payload = _payload(response)

    item = cast(list[dict[str, Any]], payload["items"])[0]
    assert item["mode"] == "self_instruction"
    assert item["self_instruction"] == "请检查提醒事项。"


@pytest.mark.asyncio
async def test_runtime_schedule_create_supports_self_instruction() -> None:
    scheduler = _FakeScheduler()
    server = RuntimeAPIServer(_context(scheduler), host="127.0.0.1", port=8788)
    request = _JsonRequest(
        _json={
            "task_id": "task_self",
            "task_name": "future self",
            "cron_expression": "0 9 * * *",
            "mode": "self_instruction",
            "self_instruction": "请总结昨天的待办。",
            "target_type": "private",
            "target_id": 12345,
            "max_executions": 1,
        }
    )

    response = await server._schedules_create_handler(
        cast(web.Request, cast(Any, request))
    )
    payload = _payload(response)

    assert response.status == 201
    assert payload["ok"] is True
    assert payload["task"]["mode"] == "self_instruction"
    assert payload["task"]["tool_name"] == SELF_CALL_TOOL_NAME
    assert payload["task"]["self_instruction"] == "请总结昨天的待办。"
    add_call = scheduler.add_calls[0]
    assert add_call["tool_args"] == {"prompt": "请总结昨天的待办。"}
    assert add_call["execution_mode"] == "serial"


@pytest.mark.asyncio
async def test_runtime_schedule_create_rejects_invalid_cron() -> None:
    scheduler = _FakeScheduler()
    server = RuntimeAPIServer(_context(scheduler), host="127.0.0.1", port=8788)
    request = _JsonRequest(
        _json={
            "cron_expression": "not a cron",
            "mode": "single",
            "tool_name": "get_current_time",
        }
    )

    response = await server._schedules_create_handler(
        cast(web.Request, cast(Any, request))
    )
    payload = _payload(response)

    assert response.status == 400
    assert payload["error"] == "cron_expression is invalid"
    assert scheduler.add_calls == []


@pytest.mark.asyncio
async def test_runtime_schedule_create_rejects_conflicting_mode_fields() -> None:
    scheduler = _FakeScheduler()
    server = RuntimeAPIServer(_context(scheduler), host="127.0.0.1", port=8788)
    request = _JsonRequest(
        _json={
            "cron_expression": "0 9 * * *",
            "mode": "single",
            "tool_name": "get_current_time",
            "self_instruction": "冲突字段",
        }
    )

    response = await server._schedules_create_handler(
        cast(web.Request, cast(Any, request))
    )
    payload = _payload(response)

    assert response.status == 400
    assert "mode conflicts" in str(payload["error"])
    assert scheduler.add_calls == []


@pytest.mark.asyncio
async def test_runtime_schedule_update_can_clear_target_and_max_runs() -> None:
    scheduler = _FakeScheduler()
    scheduler.tasks["task_daily"] = {
        "task_id": "task_daily",
        "tool_name": "get_current_time",
        "tool_args": {},
        "cron": "0 9 * * *",
        "target_id": 10001,
        "target_type": "group",
        "max_executions": 3,
    }
    server = RuntimeAPIServer(_context(scheduler), host="127.0.0.1", port=8788)
    request = _JsonRequest(
        _json={"target_id": None, "max_executions": None, "target_type": "private"},
        match_info={"task_id": "task_daily"},
    )

    response = await server._schedule_update_handler(
        cast(web.Request, cast(Any, request))
    )
    payload = _payload(response)

    assert payload["ok"] is True
    update_call = scheduler.update_calls[0]
    assert update_call["target_id"] is None
    assert update_call["target_id_provided"] is True
    assert update_call["max_executions"] is None
    assert update_call["max_executions_provided"] is True
    assert payload["task"]["target_id"] is None
    assert payload["task"]["max_executions"] is None
    assert payload["task"]["target_type"] == "private"


@pytest.mark.asyncio
async def test_runtime_schedule_update_accepts_existing_legacy_unicode_task_id() -> (
    None
):
    scheduler = _FakeScheduler()
    task_id = "task_每天早上8点发一张表情包_8d18"
    scheduler.tasks[task_id] = {
        "task_id": task_id,
        "task_name": "旧任务",
        "tool_name": "get_current_time",
        "tool_args": {},
        "cron": "0 8 * * *",
        "target_id": 1067860266,
        "target_type": "group",
    }
    server = RuntimeAPIServer(_context(scheduler), host="127.0.0.1", port=8788)
    request = _JsonRequest(
        _json={"task_name": "每天早上8点发一张表情包"},
        match_info={"task_id": task_id},
    )

    response = await server._schedule_update_handler(
        cast(web.Request, cast(Any, request))
    )
    payload = _payload(response)

    assert response.status == 200
    assert payload["ok"] is True
    assert scheduler.update_calls[0]["task_id"] == task_id


@pytest.mark.asyncio
async def test_runtime_schedule_delete_missing_returns_404() -> None:
    scheduler = _FakeScheduler()
    server = RuntimeAPIServer(_context(scheduler), host="127.0.0.1", port=8788)
    request = SimpleNamespace(match_info={"task_id": "missing_task"})

    response = await server._schedule_delete_handler(
        cast(web.Request, cast(Any, request))
    )
    payload = _payload(response)

    assert response.status == 404
    assert payload["error"] == "Schedule task not found"
    assert scheduler.remove_calls == []
