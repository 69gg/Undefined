from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from Undefined.context import RequestContext
from Undefined.skills.toolsets.messages.send_private_message.handler import execute
from Undefined.utils.coerce import was_message_sent


def _build_runtime_config() -> Any:
    return SimpleNamespace(
        is_private_allowed=lambda _uid: True,
    )


@pytest.mark.asyncio
async def test_send_private_message_callback_passes_reply_to() -> None:
    send_private_message_callback = AsyncMock()
    context: dict[str, Any] = {
        "user_id": 12345,
        "request_id": "req-private-1",
        "runtime_config": _build_runtime_config(),
        "send_private_message_callback": send_private_message_callback,
    }

    result = await execute(
        {
            "message": "hello direct private",
            "reply_to": 88888,
        },
        context,
    )

    assert result == "私聊消息已发送给用户 12345"
    send_private_message_callback.assert_awaited_once_with(
        12345, "hello direct private", reply_to=88888
    )
    assert context["message_sent_this_turn"] is True


@pytest.mark.asyncio
async def test_send_private_message_marks_request_context_when_context_is_copied() -> (
    None
):
    send_private_message_callback = AsyncMock()
    context: dict[str, Any] = {
        "user_id": 12345,
        "request_id": "req-private-context",
        "runtime_config": _build_runtime_config(),
        "send_private_message_callback": send_private_message_callback,
    }

    async with RequestContext(request_type="private", user_id=12345) as req_ctx:
        result = await execute({"message": "hello direct private"}, dict(context))

        assert result == "私聊消息已发送给用户 12345"
        assert was_message_sent(req_ctx) is True

    assert "message_sent_this_turn" not in context


@pytest.mark.asyncio
async def test_send_private_message_returns_sent_message_id_when_available() -> None:
    sender = SimpleNamespace(
        send_private_message=AsyncMock(return_value=99999),
    )
    context: dict[str, Any] = {
        "user_id": 12345,
        "request_id": "req-private-2",
        "runtime_config": _build_runtime_config(),
        "sender": sender,
    }

    result = await execute(
        {
            "message": "hello sender private",
        },
        context,
    )

    assert result == "私聊消息已发送给用户 12345（message_id=99999）"
    sender.send_private_message.assert_awaited_once_with(
        12345,
        "hello sender private",
        reply_to=None,
        history_message="hello sender private",
    )
