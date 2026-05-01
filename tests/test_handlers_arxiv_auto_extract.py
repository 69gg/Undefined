from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

import Undefined.handlers as handlers_module
from Undefined.handlers import MessageHandler
from Undefined.skills.auto_pipeline import AutoPipelineRegistry


@pytest.mark.asyncio
async def test_private_message_runs_arxiv_auto_extract_before_ai_reply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        handlers_module,
        "parse_message_content_for_history",
        AsyncMock(return_value="arxiv 2501.01234"),
    )

    handler: Any = MessageHandler.__new__(MessageHandler)
    handler.config = SimpleNamespace(
        bot_qq=10000,
        is_private_allowed=lambda _uid: True,
        access_control_enabled=lambda: False,
        should_process_private_message=lambda: True,
        bilibili_auto_extract_enabled=False,
        arxiv_auto_extract_enabled=True,
        is_arxiv_auto_extract_allowed_private=lambda _uid: True,
    )
    handler.onebot = SimpleNamespace(
        get_stranger_info=AsyncMock(return_value={"nickname": "测试用户"}),
        get_msg=AsyncMock(),
        get_forward_msg=AsyncMock(),
    )
    handler.sender = SimpleNamespace()
    handler.history_manager = SimpleNamespace(add_private_message=AsyncMock())
    handler.ai_coordinator = SimpleNamespace(
        model_pool=SimpleNamespace(
            handle_private_message=AsyncMock(return_value=False)
        ),
        handle_private_reply=AsyncMock(),
    )
    handler.command_dispatcher = SimpleNamespace(
        parse_command=MagicMock(return_value=None)
    )
    handler._background_tasks = set()
    handler._extract_arxiv_ids = MagicMock(return_value=["2501.01234"])
    handler._handle_arxiv_extract = AsyncMock()
    handler.auto_pipeline_registry = AutoPipelineRegistry()
    handler.auto_pipeline_registry.load_items()
    handler._spawn_background_task = MagicMock()

    event = {
        "post_type": "message",
        "message_type": "private",
        "user_id": 20001,
        "message_id": 30001,
        "message": [{"type": "text", "data": {"text": "arxiv 2501.01234"}}],
        "sender": {"user_id": 20001, "nickname": "测试用户"},
    }

    await handler.handle_message(event)

    handler._extract_arxiv_ids.assert_called_once()
    handler._handle_arxiv_extract.assert_awaited_once_with(
        20001,
        ["2501.01234"],
        "private",
    )
    handler._spawn_background_task.assert_not_called()
    handler.ai_coordinator.model_pool.handle_private_message.assert_not_called()
    handler.command_dispatcher.parse_command.assert_not_called()
    handler.ai_coordinator.handle_private_reply.assert_awaited_once()
