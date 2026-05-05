from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

import Undefined.handlers as handlers_module
from Undefined.handlers import MessageHandler
from Undefined.skills.pipelines import PipelineRegistry


@pytest.mark.asyncio
async def test_message_handler_initializes_pipelines_async() -> None:
    class _FakePipelineRegistry:
        def __init__(self) -> None:
            self.load_count = 0
            self.started: list[tuple[float, float]] = []

        async def load_items_async(self) -> None:
            await asyncio.sleep(0)
            self.load_count += 1

        def start_hot_reload(self, *, interval: float, debounce: float) -> None:
            self.started.append((interval, debounce))

    registry = _FakePipelineRegistry()
    handler: Any = MessageHandler.__new__(MessageHandler)
    handler.config = SimpleNamespace(
        skills_hot_reload=True,
        skills_hot_reload_interval=3.0,
        skills_hot_reload_debounce=0.75,
    )
    handler.pipeline_registry = registry
    handler._pipelines_initialized = False

    await asyncio.gather(
        handler.init_pipelines(),
        handler.init_pipelines(),
    )
    await handler.init_pipelines()

    assert registry.load_count == 1
    assert registry.started == [(3.0, 0.75)]
    assert handler._pipelines_initialized is True


@pytest.mark.asyncio
async def test_pipelines_initializes_when_flag_missing() -> None:
    class _FakePipelineRegistry:
        def __init__(self) -> None:
            self.loaded = False
            self.run_context: dict[str, Any] | None = None

        async def load_items_async(self) -> None:
            self.loaded = True

        async def run(self, context: dict[str, Any]) -> list[object]:
            self.run_context = context
            return [object()] if self.loaded else []

    registry = _FakePipelineRegistry()
    handler: Any = MessageHandler.__new__(MessageHandler)
    handler.config = SimpleNamespace(skills_hot_reload=False)
    handler.sender = SimpleNamespace()
    handler.onebot = SimpleNamespace()
    handler.pipeline_registry = registry
    handler._extract_bilibili_ids = AsyncMock(return_value=[])
    handler._extract_arxiv_ids = MagicMock(return_value=[])
    handler._extract_github_repo_ids = MagicMock(return_value=[])
    handler._handle_bilibili_extract = AsyncMock()
    handler._handle_arxiv_extract = AsyncMock()
    handler._handle_github_extract = AsyncMock()

    handled = await handler._run_pipelines(
        target_id=20001,
        target_type="private",
        text="hello",
        message_content=[],
    )

    assert handled is True
    assert registry.loaded is True
    assert registry.run_context is not None
    assert handler._pipelines_initialized is True


@pytest.mark.asyncio
async def test_pipelines_processes_all_matches() -> None:
    handler: Any = MessageHandler.__new__(MessageHandler)
    handler.sender = SimpleNamespace()
    handler.onebot = SimpleNamespace()
    handler.config = SimpleNamespace(
        bilibili_auto_extract_enabled=True,
        is_bilibili_auto_extract_allowed_private=lambda _uid: True,
        arxiv_auto_extract_enabled=True,
        is_arxiv_auto_extract_allowed_private=lambda _uid: True,
        github_auto_extract_enabled=True,
        is_github_auto_extract_allowed_private=lambda _uid: True,
    )
    handler._extract_bilibili_ids = AsyncMock(return_value=["BV1xx411c7mD"])
    handler._extract_arxiv_ids = MagicMock(return_value=["2501.01234"])
    handler._extract_github_repo_ids = MagicMock(return_value=["69gg/Undefined"])
    handler._handle_bilibili_extract = AsyncMock()
    handler._handle_arxiv_extract = AsyncMock()
    handler._handle_github_extract = AsyncMock()
    handler.pipeline_registry = PipelineRegistry()
    handler.pipeline_registry.load_items()

    handled = await handler._run_pipelines(
        target_id=20001,
        target_type="private",
        text="BV1xx411c7mD 69gg/Undefined",
        message_content=[],
    )

    assert handled is True
    handler._handle_bilibili_extract.assert_awaited_once_with(
        20001,
        ["BV1xx411c7mD"],
        "private",
    )
    handler._handle_arxiv_extract.assert_awaited_once_with(
        20001,
        ["2501.01234"],
        "private",
    )
    handler._handle_github_extract.assert_awaited_once_with(
        20001,
        ["69gg/Undefined"],
        "private",
    )


@pytest.mark.asyncio
async def test_private_command_skips_pipelines_and_ai(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        handlers_module,
        "parse_message_content_for_history",
        AsyncMock(return_value="/help"),
    )
    command = object()
    handler: Any = MessageHandler.__new__(MessageHandler)
    handler.config = SimpleNamespace(
        bot_qq=10000,
        model_pool_enabled=True,
        is_private_allowed=lambda _uid: True,
        access_control_enabled=lambda: False,
        should_process_private_message=lambda: True,
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
        parse_command=MagicMock(return_value=command),
        dispatch_private=AsyncMock(),
    )
    handler.pipeline_registry = SimpleNamespace(
        run=AsyncMock(return_value=[]),
    )
    handler._background_tasks = set()
    handler._profile_name_refresh_cache = {}

    event = {
        "post_type": "message",
        "message_type": "private",
        "user_id": 20001,
        "message_id": 30001,
        "message": [{"type": "text", "data": {"text": "/help"}}],
        "sender": {"user_id": 20001, "nickname": "测试用户"},
    }

    await handler.handle_message(event)

    handler.command_dispatcher.dispatch_private.assert_awaited_once_with(
        user_id=20001,
        sender_id=20001,
        command=command,
    )
    handler.history_manager.add_private_message.assert_awaited_once()
    assert handler.history_manager.add_private_message.await_args is not None
    private_history = handler.history_manager.add_private_message.await_args.kwargs
    assert private_history["text_content"] == "/help"
    handler.pipeline_registry.run.assert_not_awaited()
    handler.ai_coordinator.model_pool.handle_private_message.assert_not_awaited()
    handler.ai_coordinator.handle_private_reply.assert_not_awaited()


@pytest.mark.asyncio
async def test_private_model_pool_command_runs_before_command_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        handlers_module,
        "parse_message_content_for_history",
        AsyncMock(return_value="/compare hello"),
    )
    command = object()
    handler: Any = MessageHandler.__new__(MessageHandler)
    handler.config = SimpleNamespace(
        bot_qq=10000,
        model_pool_enabled=True,
        is_private_allowed=lambda _uid: True,
        access_control_enabled=lambda: False,
        should_process_private_message=lambda: True,
    )
    handler.onebot = SimpleNamespace(
        get_stranger_info=AsyncMock(return_value={"nickname": "测试用户"}),
        get_msg=AsyncMock(),
        get_forward_msg=AsyncMock(),
    )
    handler.sender = SimpleNamespace()
    handler.history_manager = SimpleNamespace(add_private_message=AsyncMock())
    handler.ai_coordinator = SimpleNamespace(
        model_pool=SimpleNamespace(handle_private_message=AsyncMock(return_value=True)),
        handle_private_reply=AsyncMock(),
    )
    handler.command_dispatcher = SimpleNamespace(
        parse_command=MagicMock(return_value=command),
        dispatch_private=AsyncMock(),
    )
    handler.pipeline_registry = SimpleNamespace(run=AsyncMock(return_value=[]))
    handler._background_tasks = set()
    handler._profile_name_refresh_cache = {}
    handler._collect_message_attachments = AsyncMock(return_value=[])
    handler._extract_bilibili_ids = AsyncMock(return_value=[])
    handler._extract_arxiv_ids = MagicMock(return_value=[])
    handler._extract_github_repo_ids = MagicMock(return_value=[])
    handler._handle_bilibili_extract = AsyncMock()
    handler._handle_arxiv_extract = AsyncMock()
    handler._handle_github_extract = AsyncMock()
    handler._schedule_profile_display_name_refresh = MagicMock()
    handler._schedule_meme_ingest = MagicMock()

    event = {
        "post_type": "message",
        "message_type": "private",
        "user_id": 20001,
        "message_id": 30001,
        "message": [{"type": "text", "data": {"text": "/compare hello"}}],
        "sender": {"user_id": 20001, "nickname": "测试用户"},
    }

    await handler.handle_message(event)

    handler.ai_coordinator.model_pool.handle_private_message.assert_awaited_once_with(
        20001,
        "/compare hello",
    )
    handler.command_dispatcher.parse_command.assert_not_called()
    handler.command_dispatcher.dispatch_private.assert_not_awaited()
    handler.pipeline_registry.run.assert_not_awaited()
    handler.ai_coordinator.handle_private_reply.assert_not_awaited()


@pytest.mark.asyncio
async def test_private_message_starting_with_select_does_not_touch_model_pool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        handlers_module,
        "parse_message_content_for_history",
        AsyncMock(return_value="选择 69gg/Undefined 看看"),
    )
    handler: Any = MessageHandler.__new__(MessageHandler)
    handler.config = SimpleNamespace(
        bot_qq=10000,
        is_private_allowed=lambda _uid: True,
        access_control_enabled=lambda: False,
        should_process_private_message=lambda: True,
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
        parse_command=MagicMock(return_value=None),
        dispatch_private=AsyncMock(),
    )
    handler.pipeline_registry = SimpleNamespace(run=AsyncMock(return_value=[]))
    handler._pipelines_initialized = True
    handler._background_tasks = set()
    handler._profile_name_refresh_cache = {}
    handler._collect_message_attachments = AsyncMock(return_value=[])
    handler._extract_bilibili_ids = AsyncMock(return_value=[])
    handler._extract_arxiv_ids = MagicMock(return_value=[])
    handler._extract_github_repo_ids = MagicMock(return_value=[])
    handler._handle_bilibili_extract = AsyncMock()
    handler._handle_arxiv_extract = AsyncMock()
    handler._handle_github_extract = AsyncMock()
    handler._schedule_profile_display_name_refresh = MagicMock()
    handler._schedule_meme_ingest = MagicMock()

    event = {
        "post_type": "message",
        "message_type": "private",
        "user_id": 20001,
        "message_id": 30001,
        "message": [{"type": "text", "data": {"text": "选择 69gg/Undefined 看看"}}],
        "sender": {"user_id": 20001, "nickname": "测试用户"},
    }

    await handler.handle_message(event)

    handler.ai_coordinator.model_pool.handle_private_message.assert_not_awaited()
    handler.pipeline_registry.run.assert_awaited_once()
    handler.ai_coordinator.handle_private_reply.assert_awaited_once()


@pytest.mark.asyncio
async def test_private_model_pool_command_ignored_when_pool_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        handlers_module,
        "parse_message_content_for_history",
        AsyncMock(return_value="/compare hello"),
    )
    handler: Any = MessageHandler.__new__(MessageHandler)
    handler.config = SimpleNamespace(
        bot_qq=10000,
        model_pool_enabled=False,
        is_private_allowed=lambda _uid: True,
        access_control_enabled=lambda: False,
        should_process_private_message=lambda: True,
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
        parse_command=MagicMock(return_value=None),
        dispatch_private=AsyncMock(),
    )
    handler.pipeline_registry = SimpleNamespace(run=AsyncMock(return_value=[]))
    handler._pipelines_initialized = True
    handler._background_tasks = set()
    handler._profile_name_refresh_cache = {}
    handler._collect_message_attachments = AsyncMock(return_value=[])
    handler._extract_bilibili_ids = AsyncMock(return_value=[])
    handler._extract_arxiv_ids = MagicMock(return_value=[])
    handler._extract_github_repo_ids = MagicMock(return_value=[])
    handler._handle_bilibili_extract = AsyncMock()
    handler._handle_arxiv_extract = AsyncMock()
    handler._handle_github_extract = AsyncMock()
    handler._schedule_profile_display_name_refresh = MagicMock()
    handler._schedule_meme_ingest = MagicMock()

    event = {
        "post_type": "message",
        "message_type": "private",
        "user_id": 20001,
        "message_id": 30001,
        "message": [{"type": "text", "data": {"text": "/compare hello"}}],
        "sender": {"user_id": 20001, "nickname": "测试用户"},
    }

    await handler.handle_message(event)

    handler.ai_coordinator.model_pool.handle_private_message.assert_not_awaited()
    handler.command_dispatcher.parse_command.assert_called_once_with("/compare hello")
    handler.pipeline_registry.run.assert_awaited_once()
    handler.ai_coordinator.handle_private_reply.assert_awaited_once()


@pytest.mark.asyncio
async def test_group_command_skips_pipelines_and_ai(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        handlers_module,
        "parse_message_content_for_history",
        AsyncMock(return_value="/help"),
    )
    command = object()
    handler: Any = MessageHandler.__new__(MessageHandler)
    handler.config = SimpleNamespace(
        bot_qq=10000,
        is_group_allowed=lambda _gid: True,
        access_control_enabled=lambda: False,
        should_process_group_message=lambda is_at_bot=False: True,
        process_every_message=True,
        keyword_reply_enabled=False,
        repeat_enabled=False,
    )
    handler.onebot = SimpleNamespace(
        get_group_info=AsyncMock(return_value={"group_name": "测试群"}),
        get_msg=AsyncMock(),
        get_forward_msg=AsyncMock(),
    )
    handler.history_manager = SimpleNamespace(add_group_message=AsyncMock())
    handler.ai_coordinator = SimpleNamespace(
        _is_at_bot=MagicMock(return_value=True),
        handle_auto_reply=AsyncMock(),
    )
    handler.command_dispatcher = SimpleNamespace(
        parse_command=MagicMock(return_value=command),
        dispatch=AsyncMock(),
    )
    handler.pipeline_registry = SimpleNamespace(
        run=AsyncMock(return_value=[]),
    )
    handler._schedule_profile_display_name_refresh = MagicMock()
    handler._schedule_meme_ingest = MagicMock()
    handler._background_tasks = set()

    event = {
        "post_type": "message",
        "message_type": "group",
        "group_id": 30001,
        "user_id": 20001,
        "message_id": 30001,
        "sender": {
            "user_id": 20001,
            "card": "测试用户",
            "nickname": "测试用户",
            "role": "member",
            "title": "",
        },
        "message": [{"type": "text", "data": {"text": "/help"}}],
    }

    await handler.handle_message(event)

    handler.command_dispatcher.dispatch.assert_awaited_once_with(
        30001,
        20001,
        command,
    )
    handler.history_manager.add_group_message.assert_awaited_once()
    assert handler.history_manager.add_group_message.await_args is not None
    group_history = handler.history_manager.add_group_message.await_args.kwargs
    assert group_history["text_content"] == "/help"
    handler.pipeline_registry.run.assert_not_awaited()
    handler.ai_coordinator.handle_auto_reply.assert_not_awaited()
