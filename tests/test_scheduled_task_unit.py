"""ScheduledTask / ToolCall 序列化 单元测试"""

from __future__ import annotations

from typing import Any


from Undefined.scheduled_task_storage import ScheduledTask, ToolCall


# ---------------------------------------------------------------------------
# ToolCall
# ---------------------------------------------------------------------------


class TestToolCall:
    def test_fields(self) -> None:
        tc = ToolCall(tool_name="search", tool_args={"q": "test"})
        assert tc.tool_name == "search"
        assert tc.tool_args == {"q": "test"}


# ---------------------------------------------------------------------------
# ScheduledTask — to_dict / from_dict 往返
# ---------------------------------------------------------------------------


def _sample_task_dict() -> dict[str, Any]:
    return {
        "task_id": "task-001",
        "tool_name": "search",
        "tool_args": {"q": "test"},
        "cron": "0 9 * * *",
        "target_id": 12345,
        "target_type": "group",
        "task_name": "每日搜索",
        "max_executions": 10,
        "current_executions": 3,
        "created_at": "2025-01-01T00:00:00",
        "context_id": "ctx-1",
        "tools": [
            {"tool_name": "search", "tool_args": {"q": "test"}},
            {"tool_name": "notify", "tool_args": {"msg": "done"}},
        ],
        "execution_mode": "parallel",
    }


class TestScheduledTaskRoundtrip:
    def test_basic_roundtrip(self) -> None:
        d = _sample_task_dict()
        task = ScheduledTask.from_dict(d)
        restored = task.to_dict()
        assert restored["task_id"] == "task-001"
        assert restored["cron"] == "0 9 * * *"
        assert restored["execution_mode"] == "parallel"
        assert len(restored["tools"]) == 2

    def test_tools_are_toolcall_instances(self) -> None:
        d = _sample_task_dict()
        task = ScheduledTask.from_dict(d)
        assert task.tools is not None
        for tc in task.tools:
            assert isinstance(tc, ToolCall)

    def test_to_dict_tools_are_dicts(self) -> None:
        d = _sample_task_dict()
        task = ScheduledTask.from_dict(d)
        restored = task.to_dict()
        for tool in restored["tools"]:
            assert isinstance(tool, dict)
            assert "tool_name" in tool


# ---------------------------------------------------------------------------
# 向后兼容 — 旧格式无 tools
# ---------------------------------------------------------------------------


class TestScheduledTaskBackwardCompat:
    def test_legacy_without_tools_field(self) -> None:
        """旧格式只有 tool_name/tool_args，没有 tools 字段。"""
        d: dict[str, Any] = {
            "task_id": "legacy-1",
            "tool_name": "old_tool",
            "tool_args": {"key": "val"},
            "cron": "*/5 * * * *",
            "target_id": None,
            "target_type": "private",
            "task_name": "旧任务",
            "max_executions": None,
        }
        task = ScheduledTask.from_dict(d)
        assert task.tools is not None
        assert len(task.tools) == 1
        assert task.tools[0].tool_name == "old_tool"
        assert task.tools[0].tool_args == {"key": "val"}

    def test_legacy_empty_tools_uses_tool_name(self) -> None:
        """tools 为空列表时，回退到 tool_name。"""
        d: dict[str, Any] = {
            "task_id": "legacy-2",
            "tool_name": "fallback",
            "tool_args": {},
            "tools": [],
            "cron": "0 0 * * *",
            "target_id": 1,
            "target_type": "group",
            "task_name": "fallback task",
            "max_executions": None,
        }
        task = ScheduledTask.from_dict(d)
        assert task.tools is not None
        assert len(task.tools) == 1
        assert task.tools[0].tool_name == "fallback"


# ---------------------------------------------------------------------------
# 可选字段缺失
# ---------------------------------------------------------------------------


class TestScheduledTaskOptionalFields:
    def test_missing_context_id(self) -> None:
        d: dict[str, Any] = {
            "task_id": "t1",
            "tool_name": "x",
            "tool_args": {},
            "cron": "0 0 * * *",
            "target_id": None,
            "target_type": "group",
            "task_name": "n",
            "max_executions": None,
        }
        task = ScheduledTask.from_dict(d)
        assert task.context_id is None

    def test_missing_current_executions(self) -> None:
        d: dict[str, Any] = {
            "task_id": "t2",
            "tool_name": "x",
            "tool_args": {},
            "cron": "0 0 * * *",
            "target_id": 1,
            "target_type": "private",
            "task_name": "n",
            "max_executions": 5,
        }
        task = ScheduledTask.from_dict(d)
        assert task.current_executions == 0

    def test_missing_created_at(self) -> None:
        d: dict[str, Any] = {
            "task_id": "t3",
            "tool_name": "x",
            "tool_args": {},
            "cron": "0 0 * * *",
            "target_id": None,
            "target_type": "group",
            "task_name": "n",
            "max_executions": None,
        }
        task = ScheduledTask.from_dict(d)
        assert task.created_at == ""

    def test_default_execution_mode(self) -> None:
        d: dict[str, Any] = {
            "task_id": "t4",
            "tool_name": "x",
            "tool_args": {},
            "cron": "0 0 * * *",
            "target_id": None,
            "target_type": "group",
            "task_name": "n",
            "max_executions": None,
        }
        task = ScheduledTask.from_dict(d)
        assert task.execution_mode == "serial"

    def test_max_executions_none(self) -> None:
        d: dict[str, Any] = {
            "task_id": "t5",
            "tool_name": "x",
            "tool_args": {},
            "cron": "0 0 * * *",
            "target_id": None,
            "target_type": "group",
            "task_name": "n",
            "max_executions": None,
        }
        task = ScheduledTask.from_dict(d)
        assert task.max_executions is None
