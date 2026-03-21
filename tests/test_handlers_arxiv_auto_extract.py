from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

import Undefined.handlers as handlers_module
from Undefined.handlers import MessageHandler


@pytest.mark.asyncio
async def test_private_message_schedules_arxiv_auto_extract(
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
    handler.history_manager = SimpleNamespace(add_private_message=AsyncMock())
    handler.ai_coordinator = SimpleNamespace(
        model_pool=SimpleNamespace(
            handle_private_message=AsyncMock(return_value=False)
        ),
        handle_private_reply=AsyncMock(),
    )
    handler.command_dispatcher = SimpleNamespace(parse_command=lambda _text: None)
    handler._background_tasks = set()
    handler._extract_arxiv_ids = MagicMock(return_value=["2501.01234"])

    def _fake_spawn_background_task(_name: str, coroutine: Any) -> None:
        coroutine.close()

    handler._spawn_background_task = MagicMock(side_effect=_fake_spawn_background_task)

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
    handler._spawn_background_task.assert_called_once()
    handler.ai_coordinator.handle_private_reply.assert_not_called()
