from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

from Undefined.skills.toolsets.scheduler.create_schedule_task.handler import (
    execute as create_schedule_task_execute,
)
from Undefined.skills.toolsets.scheduler.list_schedule_tasks.handler import (
    execute as list_schedule_tasks_execute,
)
from Undefined.skills.toolsets.scheduler.update_schedule_task.handler import (
    execute as update_schedule_task_execute,
)
from Undefined.utils.scheduler import SELF_CALL_TOOL_NAME, TaskScheduler


class _DummyTaskStorage:
    def load_tasks(self) -> dict[str, Any]:
        return {}

    async def save_all(self, _tasks: dict[str, Any]) -> None:
        return None


@pytest.mark.asyncio
async def test_create_schedule_task_supports_self_instruction() -> None:
    scheduler = SimpleNamespace(add_task=AsyncMock(return_value=True))
    context: dict[str, Any] = {
        "scheduler": scheduler,
        "group_id": 10001,
    }

    result = await create_schedule_task_execute(
        {
            "cron_expression": "0 9 * * *",
            "self_instruction": "明天早上先总结待办，再提醒我前三项。",
        },
        context,
    )

    assert "调用未来的自己" in result
    scheduler.add_task.assert_awaited_once()
    kwargs = scheduler.add_task.await_args.kwargs
    assert kwargs["tool_name"] == SELF_CALL_TOOL_NAME
    assert kwargs["tool_args"] == {"prompt": "明天早上先总结待办，再提醒我前三项。"}
    assert kwargs["self_instruction"] == "明天早上先总结待办，再提醒我前三项。"


@pytest.mark.asyncio
async def test_create_schedule_task_rejects_conflicting_modes() -> None:
    scheduler = SimpleNamespace(add_task=AsyncMock(return_value=True))
    context: dict[str, Any] = {
        "scheduler": scheduler,
        "group_id": 10001,
    }

    result = await create_schedule_task_execute(
        {
            "cron_expression": "*/5 * * * *",
            "tool_name": "get_current_time",
            "self_instruction": "冲突参数",
        },
        context,
    )

    assert "不能同时使用" in result
    scheduler.add_task.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_schedule_task_supports_self_instruction() -> None:
    scheduler = SimpleNamespace(update_task=AsyncMock(return_value=True))
    context: dict[str, Any] = {"scheduler": scheduler}

    result = await update_schedule_task_execute(
        {
            "task_id": "task_demo",
            "self_instruction": "每晚 11 点帮我生成复盘提纲。",
        },
        context,
    )

    assert "已成功修改" in result
    scheduler.update_task.assert_awaited_once()
    kwargs = scheduler.update_task.await_args.kwargs
    assert kwargs["tool_name"] == SELF_CALL_TOOL_NAME
    assert kwargs["tool_args"] == {"prompt": "每晚 11 点帮我生成复盘提纲。"}
    assert kwargs["self_instruction"] == "每晚 11 点帮我生成复盘提纲。"


@pytest.mark.asyncio
async def test_list_schedule_tasks_marks_self_instruction_task() -> None:
    scheduler = SimpleNamespace(
        list_tasks=lambda: {
            "task_self_1": {
                "task_name": "future_me",
                "tool_name": SELF_CALL_TOOL_NAME,
                "tool_args": {"prompt": "明天提醒我看板更新"},
                "cron": "0 9 * * *",
                "current_executions": 0,
            }
        }
    )
    context: dict[str, Any] = {"scheduler": scheduler}

    result = await list_schedule_tasks_execute({}, context)

    assert "调用未来的自己" in result
    assert "明天提醒我看板更新" in result


@pytest.mark.asyncio
async def test_task_scheduler_execute_self_call_invokes_ai_and_sends_result() -> None:
    ai = SimpleNamespace(
        ask=AsyncMock(return_value="未来指令已执行"),
        memory_storage=SimpleNamespace(),
        runtime_config=SimpleNamespace(),
    )
    sender = SimpleNamespace(
        send_group_message=AsyncMock(),
        send_private_message=AsyncMock(),
    )
    onebot = SimpleNamespace(
        send_like=AsyncMock(),
        get_image=AsyncMock(return_value=None),
        get_forward_msg=AsyncMock(return_value=[]),
    )
    history_manager = SimpleNamespace()
    scheduler = TaskScheduler(
        ai,
        sender,
        onebot,
        history_manager,
        task_storage=cast(Any, _DummyTaskStorage()),
    )

    sent_messages: list[str] = []

    async def _send_message(message: str) -> None:
        sent_messages.append(message)

    try:
        result = await scheduler._execute_tool(
            SELF_CALL_TOOL_NAME,
            {"prompt": "请在触发时复盘并提醒我明天重点。"},
            {
                "send_message_callback": _send_message,
                "scheduled_task_id": "task_self_abc",
                "scheduled_task_name": "future-review",
            },
        )
    finally:
        scheduler.scheduler.shutdown(wait=False)

    assert result == "已执行向未来自己的指令"
    ai.ask.assert_awaited_once()
    ask_call = ai.ask.await_args
    assert ask_call.args[0] == "请在触发时复盘并提醒我明天重点。"
    assert ask_call.kwargs["scheduler"] is scheduler
    assert ask_call.kwargs["extra_context"]["scheduled_self_call"] is True
    assert ask_call.kwargs["extra_context"]["scheduled_task_id"] == "task_self_abc"
    assert ask_call.kwargs["extra_context"]["scheduled_task_name"] == "future-review"
    assert sent_messages == ["未来指令已执行"]
