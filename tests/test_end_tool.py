from __future__ import annotations

from typing import Any
from types import SimpleNamespace

import pytest

from Undefined.context import RequestContext
from Undefined.skills.tools.end.handler import execute


@pytest.mark.asyncio
async def test_end_accepts_force_string_true_case_insensitive() -> None:
    context: dict[str, Any] = {"request_id": "req-force-true"}

    result = await execute(
        {"action_summary": "已发送消息", "force": "TrUe"},
        context,
    )

    assert result == "对话已结束"
    assert context["conversation_ended"] is True


@pytest.mark.asyncio
async def test_end_rejects_when_force_string_false_and_no_message_sent() -> None:
    context: dict[str, Any] = {"request_id": "req-force-false"}

    result = await execute(
        {"action_summary": "已发送消息", "force": "FaLsE"},
        context,
    )

    assert result.startswith("拒绝结束对话")
    assert context.get("conversation_ended") is not True


@pytest.mark.asyncio
async def test_end_accepts_message_sent_flag_from_context_string_true() -> None:
    context: dict[str, Any] = {
        "request_id": "req-message-flag",
        "message_sent_this_turn": "TRUE",
    }

    result = await execute({"action_summary": "已发送消息"}, context)

    assert result == "对话已结束"
    assert context["conversation_ended"] is True


@pytest.mark.asyncio
async def test_end_accepts_message_sent_flag_from_request_context_string_true() -> None:
    context: dict[str, Any] = {"request_id": "req-request-context-flag"}

    async with RequestContext(request_type="group", group_id=1, sender_id=2) as req_ctx:
        req_ctx.set_resource("message_sent_this_turn", "YeS")
        result = await execute({"action_summary": "已发送消息"}, context)

    assert result == "对话已结束"
    assert context["conversation_ended"] is True


class _FakeHistoryManager:
    def get_recent(
        self, chat_id: str, msg_type: str, start: int, end: int
    ) -> list[dict[str, Any]]:
        assert chat_id == "1082837821"
        assert msg_type == "group"
        return [
            {
                "timestamp": "2026-02-23 19:02:11",
                "display_name": "洛泫",
                "user_id": "120218451",
                "message": "Null 说这个是竞态问题",
            }
        ]


class _FakeCognitiveService:
    def __init__(self) -> None:
        self.last_context: dict[str, Any] | None = None

    async def enqueue_job(
        self, action_summary: str, new_info: list[str], context: dict[str, Any]
    ) -> str:
        self.last_context = dict(context)
        return "job-test"


@pytest.mark.asyncio
async def test_end_enriches_historian_reference_context() -> None:
    cognitive_service = _FakeCognitiveService()
    context: dict[str, Any] = {
        "request_id": "req-historian-context",
        "request_type": "group",
        "group_id": "1082837821",
        "user_id": "120218451",
        "sender_id": "120218451",
        "history_manager": _FakeHistoryManager(),
        "cognitive_service": cognitive_service,
        "current_question": (
            '<message sender="洛泫" sender_id="120218451" group_id="1082837821" '
            'group_name="bot测试群" location="bot测试群" time="2026-02-23 19:02:12">'
            "<content>Null(1708213363)说发现了一个竞态问题</content></message>"
        ),
    }

    result = await execute(
        {"new_info": ["Null(1708213363)说发现了一个竞态问题"], "force": True},
        context,
    )

    assert result == "对话已结束"
    assert context["conversation_ended"] is True
    assert (
        context.get("historian_source_message")
        == "Null(1708213363)说发现了一个竞态问题"
    )
    assert context.get("historian_recent_messages")
    assert cognitive_service.last_context is not None
    assert cognitive_service.last_context.get("historian_source_message")
    assert cognitive_service.last_context.get("historian_recent_messages")


class _ManyHistoryManager:
    def get_recent(
        self, chat_id: str, msg_type: str, start: int, end: int
    ) -> list[dict[str, Any]]:
        return [
            {
                "timestamp": "2026-02-23 19:02:11",
                "display_name": "洛泫",
                "user_id": "120218451",
                "message": f"line-{i}-" + ("x" * 200),
            }
            for i in range(20)
        ]


@pytest.mark.asyncio
async def test_end_uses_runtime_config_for_historian_reference_limits() -> None:
    cognitive_service = _FakeCognitiveService()
    runtime_config = SimpleNamespace(
        cognitive=SimpleNamespace(
            historian_recent_messages_inject_k=2,
            historian_recent_message_line_max_len=60,
            historian_source_message_max_len=40,
        )
    )
    long_content = "A" * 300
    context: dict[str, Any] = {
        "request_id": "req-historian-limits",
        "request_type": "group",
        "group_id": "1082837821",
        "user_id": "120218451",
        "sender_id": "120218451",
        "history_manager": _ManyHistoryManager(),
        "cognitive_service": cognitive_service,
        "runtime_config": runtime_config,
        "current_question": (
            '<message sender="洛泫" sender_id="120218451" group_id="1082837821" '
            'group_name="bot测试群" location="bot测试群" time="2026-02-23 19:02:12">'
            f"<content>{long_content}</content></message>"
        ),
    }

    await execute({"new_info": ["测试"], "force": True}, context)

    source = str(context.get("historian_source_message", ""))
    recent = context.get("historian_recent_messages", [])
    assert len(source) <= 40
    assert isinstance(recent, list)
    assert len(recent) == 2
    assert all(
        len(str(line).split(": ", 1)[1]) <= 60 for line in recent if ": " in str(line)
    )
