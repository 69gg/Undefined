from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

import Undefined.handlers as handlers_module
from Undefined.handlers import MessageHandler
import Undefined.github.sender as github_sender_module
from Undefined.skills.pipelines import PipelineRegistry


@pytest.mark.asyncio
async def test_private_message_runs_github_auto_extract_before_ai_reply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        handlers_module,
        "parse_message_content_for_history",
        AsyncMock(return_value="repo 69gg/Undefined"),
    )

    handler: Any = MessageHandler.__new__(MessageHandler)
    handler.config = SimpleNamespace(
        bot_qq=10000,
        is_private_allowed=lambda _uid: True,
        access_control_enabled=lambda: False,
        should_process_private_message=lambda: True,
        bilibili_auto_extract_enabled=False,
        arxiv_auto_extract_enabled=False,
        github_auto_extract_enabled=True,
        is_github_auto_extract_allowed_private=lambda _uid: True,
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
    handler._extract_github_repo_ids = MagicMock(return_value=["69gg/Undefined"])
    handler._handle_github_extract = AsyncMock()
    handler.pipeline_registry = PipelineRegistry()
    handler.pipeline_registry.load_items()
    handler._spawn_background_task = MagicMock()

    event = {
        "post_type": "message",
        "message_type": "private",
        "user_id": 20001,
        "message_id": 30001,
        "message": [{"type": "text", "data": {"text": "69gg/Undefined"}}],
        "sender": {"user_id": 20001, "nickname": "测试用户"},
    }

    await handler.handle_message(event)

    handler._extract_github_repo_ids.assert_called_once()
    handler._handle_github_extract.assert_awaited_once_with(
        20001,
        ["69gg/Undefined"],
        "private",
    )
    handler._spawn_background_task.assert_not_called()
    handler.ai_coordinator.model_pool.handle_private_message.assert_not_called()
    handler.command_dispatcher.parse_command.assert_called_once_with("69gg/Undefined")
    handler.ai_coordinator.handle_private_reply.assert_awaited_once()


@pytest.mark.asyncio
async def test_github_auto_extract_logs_exception_type_and_repr(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    sender_calls: list[dict[str, Any]] = []

    async def fake_send_github_repo_card(**kwargs: Any) -> str:
        sender_calls.append(kwargs)
        raise httpx.ConnectError("")

    monkeypatch.setattr(
        github_sender_module,
        "send_github_repo_card",
        fake_send_github_repo_card,
    )

    handler: Any = MessageHandler.__new__(MessageHandler)
    handler.config = SimpleNamespace(
        github_auto_extract_max_items=3,
        github_request_timeout_seconds=11.0,
        github_request_retries=4,
    )
    handler.sender = SimpleNamespace()

    with caplog.at_level(logging.ERROR, logger="Undefined.handlers.auto_extract"):
        await handler._handle_github_extract(
            target_id=1067860266,
            repo_ids=["69gg/Undefined"],
            target_type="group",
        )

    log_text = caplog.text
    assert "自动提取跳过 69gg/Undefined" in log_text
    assert "exc_type=ConnectError" in log_text
    assert "ConnectError('')" in log_text
    assert sender_calls == [
        {
            "repo_id": "69gg/Undefined",
            "sender": handler.sender,
            "target_type": "group",
            "target_id": 1067860266,
            "request_timeout": 11.0,
            "request_retries": 4,
            "context": {
                "request_id": "github_auto_extract:group:1067860266:69gg/Undefined"
            },
        }
    ]
