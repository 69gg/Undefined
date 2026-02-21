from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from Undefined.context import RequestContext
from Undefined.skills.toolsets.messages.send_poke.handler import execute


def _build_runtime_config() -> Any:
    return SimpleNamespace(
        bot_qq=123456,
        is_group_allowed=lambda _gid: True,
        is_private_allowed=lambda _uid: True,
    )


@pytest.mark.asyncio
async def test_send_poke_group_default_target_writes_group_history() -> None:
    history_manager = SimpleNamespace(
        add_group_message=AsyncMock(),
        add_private_message=AsyncMock(),
    )
    sender = SimpleNamespace(
        send_group_poke=AsyncMock(),
        send_private_poke=AsyncMock(),
    )
    context: dict[str, Any] = {
        "request_type": "group",
        "group_id": 10001,
        "user_id": 20002,
        "sender_id": 20002,
        "request_id": "req-1",
        "runtime_config": _build_runtime_config(),
        "history_manager": history_manager,
        "sender": sender,
    }

    result = await execute({}, context)

    assert result == "已在群 10001 拍了拍 QQ20002"
    sender.send_group_poke.assert_called_once_with(10001, 20002)
    history_manager.add_group_message.assert_called_once()
    call = history_manager.add_group_message.call_args
    assert call.kwargs["group_id"] == 10001
    assert call.kwargs["sender_id"] == 123456
    assert call.kwargs["text_content"] == "(拍了拍 QQ20002)"
    assert call.kwargs["sender_nickname"] == "Bot"
    assert call.kwargs["group_name"] == ""
    history_manager.add_private_message.assert_not_called()
    assert context["message_sent_this_turn"] is True


@pytest.mark.asyncio
async def test_send_poke_private_default_target_writes_private_history() -> None:
    history_manager = SimpleNamespace(
        add_group_message=AsyncMock(),
        add_private_message=AsyncMock(),
    )
    onebot_client = SimpleNamespace(send_private_poke=AsyncMock())
    context: dict[str, Any] = {
        "request_type": "private",
        "user_id": 30003,
        "sender_id": 30003,
        "request_id": "req-2",
        "runtime_config": _build_runtime_config(),
        "history_manager": history_manager,
        "onebot_client": onebot_client,
    }

    result = await execute({}, context)

    assert result == "已拍了拍 QQ30003"
    onebot_client.send_private_poke.assert_called_once_with(30003)
    history_manager.add_private_message.assert_called_once()
    call = history_manager.add_private_message.call_args
    assert call.kwargs["user_id"] == 30003
    assert call.kwargs["text_content"] == "(拍了拍 QQ30003)"
    assert call.kwargs["display_name"] == "Bot"
    assert call.kwargs["user_name"] == "Bot"
    history_manager.add_group_message.assert_not_called()
    assert context["message_sent_this_turn"] is True


@pytest.mark.asyncio
async def test_send_poke_explicit_group_and_target_user() -> None:
    history_manager = SimpleNamespace(
        add_group_message=AsyncMock(),
        add_private_message=AsyncMock(),
    )
    onebot_client = SimpleNamespace(send_group_poke=AsyncMock())
    context: dict[str, Any] = {
        "request_type": "private",
        "user_id": 40004,
        "sender_id": 40004,
        "request_id": "req-3",
        "runtime_config": _build_runtime_config(),
        "history_manager": history_manager,
        "onebot_client": onebot_client,
    }

    result = await execute(
        {"target_type": "group", "target_id": 88888, "target_user_id": 99999},
        context,
    )

    assert result == "已在群 88888 拍了拍 QQ99999"
    onebot_client.send_group_poke.assert_called_once_with(88888, 99999)
    history_manager.add_group_message.assert_called_once()
    call = history_manager.add_group_message.call_args
    assert call.kwargs["group_id"] == 88888
    assert call.kwargs["sender_id"] == 123456
    assert call.kwargs["text_content"] == "(拍了拍 QQ99999)"
    history_manager.add_private_message.assert_not_called()


@pytest.mark.asyncio
async def test_send_poke_infers_from_request_context_when_context_missing() -> None:
    sender = SimpleNamespace(
        send_group_poke=AsyncMock(),
        send_private_poke=AsyncMock(),
    )
    context: dict[str, Any] = {
        "sender": sender,
        "runtime_config": _build_runtime_config(),
    }

    async with RequestContext(
        request_type="group",
        group_id=70007,
        user_id=80008,
        sender_id=80008,
    ):
        result = await execute({"target_type": "group"}, context)

    assert result == "已在群 70007 拍了拍 QQ80008"
    sender.send_group_poke.assert_called_once_with(70007, 80008)
    assert context["message_sent_this_turn"] is True
