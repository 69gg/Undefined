from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from Undefined.skills.toolsets.messages.send_message.handler import execute


def _build_runtime_config() -> Any:
    return SimpleNamespace(
        is_group_allowed=lambda _gid: True,
        is_private_allowed=lambda _uid: True,
    )


@pytest.mark.asyncio
async def test_send_message_private_passes_context_group_as_preferred_temp_group() -> (
    None
):
    sender = SimpleNamespace(
        send_group_message=AsyncMock(),
        send_private_message=AsyncMock(),
    )
    context: dict[str, Any] = {
        "request_type": "group",
        "group_id": 10001,
        "user_id": 20002,
        "sender_id": 20002,
        "request_id": "req-1",
        "runtime_config": _build_runtime_config(),
        "sender": sender,
    }

    result = await execute(
        {
            "target_type": "private",
            "target_id": 30003,
            "message": "hello",
        },
        context,
    )

    assert result == "消息已发送"
    sender.send_private_message.assert_called_once_with(
        30003,
        "hello",
        reply_to=None,
        preferred_temp_group_id=10001,
    )
    sender.send_group_message.assert_not_called()
    assert context["message_sent_this_turn"] is True
