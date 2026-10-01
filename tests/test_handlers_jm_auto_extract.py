from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

import Undefined.handlers as handlers_module
import Undefined.jm.sender as jm_sender_module
from Undefined.handlers import MessageHandler
from Undefined.skills.pipelines import PipelineRegistry


@pytest.mark.asyncio
async def test_private_message_runs_jm_auto_extract_before_ai_reply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        handlers_module,
        "parse_message_content_for_history",
        AsyncMock(return_value="jm350234"),
    )

    handler: Any = MessageHandler.__new__(MessageHandler)
    handler.config = SimpleNamespace(
        bot_qq=10000,
        is_private_allowed=lambda _uid: True,
        access_control_enabled=lambda: False,
        should_process_private_message=lambda: True,
        bilibili_auto_extract_enabled=False,
        arxiv_auto_extract_enabled=False,
        github_auto_extract_enabled=False,
        jm_auto_extract_enabled=True,
        jm_auto_extract_max_items=1,
        is_jm_auto_extract_allowed_private=lambda _uid: True,
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
    handler._extract_jm_ids = MagicMock(return_value=["350234"])
    handler._handle_jm_extract = AsyncMock()
    handler.pipeline_registry = PipelineRegistry()
    handler.pipeline_registry.load_items()
    handler._spawn_background_task = MagicMock()

    event = {
        "post_type": "message",
        "message_type": "private",
        "user_id": 20001,
        "message_id": 30001,
        "message": [{"type": "text", "data": {"text": "jm350234"}}],
        "sender": {"user_id": 20001, "nickname": "测试用户"},
    }

    await handler.handle_message(event)

    handler._extract_jm_ids.assert_called_once()
    handler._handle_jm_extract.assert_awaited_once_with(20001, ["350234"], "private")
    handler._spawn_background_task.assert_not_called()
    handler.ai_coordinator.model_pool.handle_private_message.assert_not_called()
    handler.command_dispatcher.parse_command.assert_called_once_with("jm350234")
    handler.ai_coordinator.handle_private_reply.assert_awaited_once()


@pytest.mark.asyncio
async def test_jm_auto_extract_truncates_items_and_reports_failure(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    sent: list[str] = []

    async def _send(book_id: str, **_kwargs: Any) -> str:
        sent.append(book_id)
        if book_id == "2222222":
            raise RuntimeError("源站 404")
        return f"JM{book_id} 已发送"

    monkeypatch.setattr(jm_sender_module, "send_jm_book", _send)

    handler: Any = MessageHandler.__new__(MessageHandler)
    handler.config = SimpleNamespace(jm_auto_extract_max_items=2)
    handler.sender = SimpleNamespace(send_group_message=AsyncMock())

    with caplog.at_level("INFO"):
        await handler._handle_jm_extract(
            20001, ["1111111", "2222222", "3333333"], "group"
        )

    # max_items=2：第三个车号被丢弃，不再发起下载
    assert sent == ["1111111", "2222222"]
    error_calls = handler.sender.send_group_message.await_args_list
    assert error_calls, "失败时要给会话一行提示"
    assert "JM 提取失败" in error_calls[0].args[1]
    assert "源站 404" in error_calls[0].args[1]
    assert "RuntimeError" in caplog.text


@pytest.mark.asyncio
async def test_jm_auto_extract_passes_custom_sender(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    async def _send(book_id: str, **kwargs: Any) -> str:
        captured["book_id"] = book_id
        captured["sender"] = kwargs.get("sender")
        return "ok"

    monkeypatch.setattr(jm_sender_module, "send_jm_book", _send)

    handler: Any = MessageHandler.__new__(MessageHandler)
    handler.config = SimpleNamespace(jm_auto_extract_max_items=3)
    handler.sender = SimpleNamespace(send_group_message=AsyncMock())
    address_sender = SimpleNamespace(send_group_message=AsyncMock())

    await handler._handle_jm_extract(20001, ["350234"], "group", address_sender)

    assert captured["book_id"] == "350234"
    assert captured["sender"] is address_sender


@pytest.mark.asyncio
async def test_jm_auto_extract_does_nothing_without_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called: list[str] = []

    async def _send(book_id: str, **_kwargs: Any) -> str:
        called.append(book_id)
        return "ok"

    monkeypatch.setattr(jm_sender_module, "send_jm_book", _send)

    handler: Any = MessageHandler.__new__(MessageHandler)
    handler.config = SimpleNamespace(jm_auto_extract_max_items=3)
    handler.sender = SimpleNamespace(send_group_message=AsyncMock())

    await handler._handle_jm_extract(20001, [], "group")

    assert called == []
