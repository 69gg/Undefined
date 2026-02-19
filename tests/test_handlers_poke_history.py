"""MessageHandler 拍一拍历史记录测试"""

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from Undefined.handlers import MessageHandler


def _build_handler() -> Any:
    handler: Any = MessageHandler.__new__(MessageHandler)
    handler.config = SimpleNamespace(
        bot_qq=10000,
        should_process_poke_message=lambda: True,
        is_private_allowed=lambda _uid: True,
        is_group_allowed=lambda _gid: True,
        access_control_enabled=lambda: False,
    )
    handler.history_manager = SimpleNamespace(
        add_private_message=AsyncMock(),
        add_group_message=AsyncMock(),
    )
    handler.ai_coordinator = SimpleNamespace(
        handle_private_reply=AsyncMock(),
        handle_auto_reply=AsyncMock(),
    )
    handler.onebot = SimpleNamespace(
        get_stranger_info=AsyncMock(return_value={"nickname": "测试用户"}),
        get_group_info=AsyncMock(return_value={"group_name": "测试群"}),
    )
    return handler


@pytest.mark.asyncio
async def test_private_poke_writes_history_and_triggers_reply() -> None:
    handler = _build_handler()
    event = {
        "post_type": "notice",
        "notice_type": "poke",
        "target_id": 10000,
        "group_id": 0,
        "user_id": 20001,
        "sender": {"user_id": 20001},
    }

    await handler.handle_message(event)

    handler.history_manager.add_private_message.assert_called_once()
    private_history_call = handler.history_manager.add_private_message.call_args
    assert private_history_call.kwargs["user_id"] == 20001
    assert private_history_call.kwargs["text_content"] == "(拍了拍你)"
    assert private_history_call.kwargs["display_name"] == "测试用户"
    assert private_history_call.kwargs["user_name"] == "测试用户"

    handler.ai_coordinator.handle_private_reply.assert_called_once()
    private_reply_call = handler.ai_coordinator.handle_private_reply.call_args
    assert private_reply_call.args[0] == 20001
    assert private_reply_call.args[1] == "(拍了拍你)"
    assert private_reply_call.args[2] == []
    assert private_reply_call.kwargs["is_poke"] is True
    assert private_reply_call.kwargs["sender_name"] == "20001"

    handler.history_manager.add_group_message.assert_not_called()
    handler.ai_coordinator.handle_auto_reply.assert_not_called()


@pytest.mark.asyncio
async def test_group_poke_writes_history_and_triggers_reply() -> None:
    handler = _build_handler()
    event = {
        "post_type": "notice",
        "notice_type": "poke",
        "target_id": 10000,
        "group_id": 30001,
        "user_id": 20001,
        "sender": {
            "user_id": 20001,
            "card": "群名片",
            "nickname": "群昵称",
            "role": "admin",
            "title": "头衔",
        },
    }

    await handler.handle_message(event)

    handler.history_manager.add_group_message.assert_called_once()
    group_history_call = handler.history_manager.add_group_message.call_args
    assert group_history_call.kwargs["group_id"] == 30001
    assert group_history_call.kwargs["sender_id"] == 20001
    assert group_history_call.kwargs["text_content"] == "(拍了拍你)"
    assert group_history_call.kwargs["sender_card"] == "群名片"
    assert group_history_call.kwargs["sender_nickname"] == "群昵称"
    assert group_history_call.kwargs["group_name"] == "测试群"
    assert group_history_call.kwargs["role"] == "admin"
    assert group_history_call.kwargs["title"] == "头衔"

    handler.ai_coordinator.handle_auto_reply.assert_called_once()
    group_reply_call = handler.ai_coordinator.handle_auto_reply.call_args
    assert group_reply_call.args[0] == 30001
    assert group_reply_call.args[1] == 20001
    assert group_reply_call.args[2] == "(拍了拍你)"
    assert group_reply_call.args[3] == []
    assert group_reply_call.kwargs["is_poke"] is True
    assert group_reply_call.kwargs["sender_name"] == "20001"
    assert group_reply_call.kwargs["group_name"] == "30001"

    handler.history_manager.add_private_message.assert_not_called()
    handler.ai_coordinator.handle_private_reply.assert_not_called()
