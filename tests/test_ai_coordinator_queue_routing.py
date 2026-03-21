from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

from Undefined.services.ai_coordinator import AICoordinator


@pytest.mark.asyncio
async def test_handle_auto_reply_routes_group_superadmin_to_dedicated_queue() -> None:
    coordinator: Any = object.__new__(AICoordinator)
    queue_manager = SimpleNamespace(
        add_group_superadmin_request=AsyncMock(),
        add_group_mention_request=AsyncMock(),
        add_group_normal_request=AsyncMock(),
    )
    coordinator.config = SimpleNamespace(
        superadmin_qq=10001,
        chat_model=SimpleNamespace(model_name="chat-model"),
    )
    coordinator.security = SimpleNamespace(
        detect_injection=AsyncMock(return_value=False)
    )
    coordinator.history_manager = SimpleNamespace(modify_last_group_message=AsyncMock())
    coordinator.queue_manager = queue_manager
    coordinator._is_at_bot = lambda _content: False
    coordinator._build_prompt = lambda *args, **kwargs: "prompt"

    await AICoordinator.handle_auto_reply(
        coordinator,
        group_id=12345,
        sender_id=10001,
        text="hello",
        message_content=[],
        sender_name="superadmin",
        group_name="测试群",
    )

    cast(AsyncMock, queue_manager.add_group_superadmin_request).assert_awaited_once()
    cast(AsyncMock, queue_manager.add_group_mention_request).assert_not_called()
    cast(AsyncMock, queue_manager.add_group_normal_request).assert_not_called()


@pytest.mark.asyncio
async def test_handle_auto_reply_includes_trigger_message_id_in_full_question() -> None:
    coordinator: Any = object.__new__(AICoordinator)
    queue_manager = SimpleNamespace(
        add_group_superadmin_request=AsyncMock(),
        add_group_mention_request=AsyncMock(),
        add_group_normal_request=AsyncMock(),
    )
    coordinator.config = SimpleNamespace(
        superadmin_qq=99999,
        chat_model=SimpleNamespace(model_name="chat-model"),
    )
    coordinator.security = SimpleNamespace(
        detect_injection=AsyncMock(return_value=False)
    )
    coordinator.history_manager = SimpleNamespace(modify_last_group_message=AsyncMock())
    coordinator.queue_manager = queue_manager
    coordinator._is_at_bot = lambda _content: False

    await AICoordinator.handle_auto_reply(
        coordinator,
        group_id=12345,
        sender_id=20001,
        text="hello",
        message_content=[],
        sender_name="member",
        group_name="测试群",
        trigger_message_id=54321,
    )

    await_args = cast(AsyncMock, queue_manager.add_group_normal_request).await_args
    assert await_args is not None
    request_data = await_args.args[0]
    assert 'message_id="54321"' in request_data["full_question"]


@pytest.mark.asyncio
async def test_handle_auto_reply_omits_message_id_when_trigger_missing() -> None:
    coordinator: Any = object.__new__(AICoordinator)
    queue_manager = SimpleNamespace(
        add_group_superadmin_request=AsyncMock(),
        add_group_mention_request=AsyncMock(),
        add_group_normal_request=AsyncMock(),
    )
    coordinator.config = SimpleNamespace(
        superadmin_qq=99999,
        chat_model=SimpleNamespace(model_name="chat-model"),
    )
    coordinator.security = SimpleNamespace(
        detect_injection=AsyncMock(return_value=False)
    )
    coordinator.history_manager = SimpleNamespace(modify_last_group_message=AsyncMock())
    coordinator.queue_manager = queue_manager
    coordinator._is_at_bot = lambda _content: False

    await AICoordinator.handle_auto_reply(
        coordinator,
        group_id=12345,
        sender_id=20001,
        text="hello",
        message_content=[],
        sender_name="member",
        group_name="测试群",
    )

    await_args = cast(AsyncMock, queue_manager.add_group_normal_request).await_args
    assert await_args is not None
    request_data = await_args.args[0]
    assert 'message_id="' not in request_data["full_question"]


@pytest.mark.asyncio
async def test_handle_private_reply_includes_trigger_message_id_in_full_question() -> (
    None
):
    coordinator: Any = object.__new__(AICoordinator)
    queue_manager = SimpleNamespace(
        add_superadmin_request=AsyncMock(),
        add_private_request=AsyncMock(),
    )
    coordinator.config = SimpleNamespace(
        superadmin_qq=99999,
        chat_model=SimpleNamespace(model_name="chat-model"),
    )
    coordinator.security = SimpleNamespace(
        detect_injection=AsyncMock(return_value=False)
    )
    coordinator.history_manager = SimpleNamespace(
        modify_last_private_message=AsyncMock()
    )
    coordinator.queue_manager = queue_manager
    coordinator.model_pool = SimpleNamespace(
        select_chat_config=lambda chat_model, user_id: chat_model
    )

    await AICoordinator.handle_private_reply(
        coordinator,
        user_id=20001,
        text="hello",
        message_content=[],
        sender_name="member",
        trigger_message_id=65432,
    )

    await_args = cast(AsyncMock, queue_manager.add_private_request).await_args
    assert await_args is not None
    request_data = await_args.args[0]
    assert 'message_id="65432"' in request_data["full_question"]
