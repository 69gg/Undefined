from __future__ import annotations

from typing import Any

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
