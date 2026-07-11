from __future__ import annotations

import importlib
from collections.abc import Awaitable, Callable
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, Mock

import pytest

from Undefined.context import RequestContext
from Undefined.services.coordinator import AICoordinator
from Undefined.services.coordinator.background import BackgroundMixin
from Undefined.services.message_batcher import BufferedMessage
from Undefined.services.coordinator import group as coordinator_group_module


def test_legacy_ai_coordinator_module_is_removed() -> None:
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("Undefined.services.ai_coordinator")


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


@pytest.mark.asyncio
async def test_handle_private_reply_avoids_extra_blank_line_without_attachments() -> (
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
    )

    await_args = cast(AsyncMock, queue_manager.add_private_request).await_args
    assert await_args is not None
    request_data = await_args.args[0]
    assert "</content>\n\n </message>" not in request_data["full_question"]


def test_build_prompt_limits_proactive_participation_to_technical_contexts() -> None:
    coordinator: Any = object.__new__(AICoordinator)

    prompt = AICoordinator._build_prompt(
        coordinator,
        prefix="",
        name="member",
        uid=20001,
        gid=12345,
        gname="测试群",
        loc="测试群",
        role="member",
        title="",
        time_str="2026-04-11 12:00:00",
        text="哈哈",
    )

    assert "群聊里的主动参与只保留给公开、开放的技术或项目讨论" in prompt
    assert "轻松互动、玩梗、吐槽本身不构成参与许可" in prompt
    assert "只有明确纯表情包回复才先检索表情包" in prompt
    assert "第一轮必须优先把必要文字回复做好并调用 send_message" in prompt
    assert "文字发送成功后优先考虑在后续响应轮次补一张独立表情包" in prompt
    assert "严肃答疑、代码排查、长任务推进、隐私/安全拒绝、信息不足追问" in prompt
    assert "默认先尝试 memes.search_memes" not in prompt
    assert "普通闲聊、玩梗、吐槽、轻松互动：" not in prompt


def test_format_group_message_segment_preserves_known_attachment_tag() -> None:
    coordinator: Any = object.__new__(AICoordinator)
    item = BufferedMessage(
        scope="group:12345",
        sender_id=20001,
        text='看图 <attachment uid="pic_demo"/> <attachment uid="pic_fake"/>',
        message_content=[],
        attachments=[
            {
                "uid": "pic_demo",
                "kind": "image",
                "media_type": "image",
                "display_name": "demo.png",
            }
        ],
        sender_name="member",
        arrival_time=1_700_000_000,
        is_private=False,
        group_id=12345,
        group_name="测试群",
    )

    prompt = AICoordinator._format_group_message_segment(coordinator, item)

    assert '<attachment uid="pic_demo"/>' in prompt
    assert '<attachment uid="pic_fake"/>' not in prompt
    assert "&lt;attachment uid=&quot;pic_fake&quot;/&gt;" in prompt


@pytest.mark.asyncio
async def test_execute_auto_reply_send_msg_cb_passes_history_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    coordinator: Any = object.__new__(AICoordinator)
    sender = SimpleNamespace(send_group_message=AsyncMock())
    captured_extra_context: dict[str, Any] = {}
    captured_resources: dict[str, Any] = {}

    async def _fake_ask(*_args: Any, **kwargs: Any) -> str:
        extra_context = cast(dict[str, Any], kwargs.get("extra_context", {}))
        captured_extra_context.update(extra_context)
        current_context = RequestContext.current()
        assert current_context is not None
        captured_resources.update(current_context.get_resources())
        send_message_callback = cast(
            Callable[[str], Awaitable[None]],
            kwargs["send_message_callback"],
        )
        await send_message_callback("hello group")
        return ""

    coordinator.config = SimpleNamespace(bot_qq=10000)
    coordinator.sender = sender
    coordinator.ai = SimpleNamespace(
        ask=_fake_ask,
        memory_storage=SimpleNamespace(),
        runtime_config=SimpleNamespace(),
    )
    coordinator.history_manager = SimpleNamespace()
    coordinator.onebot = SimpleNamespace(
        get_image=AsyncMock(),
        get_forward_msg=AsyncMock(),
        send_like=AsyncMock(),
    )
    coordinator.scheduler = SimpleNamespace()

    monkeypatch.setattr(
        coordinator_group_module,
        "collect_context_resources",
        lambda _vars: {},
    )

    await coordinator._execute_auto_reply(
        {
            "group_id": 12345,
            "sender_id": 20001,
            "sender_name": "member",
            "group_name": "测试群",
            "full_question": "prompt",
            "message_ids": ["101", "102"],
            "batched_count": 2,
        }
    )

    sender.send_group_message.assert_awaited_once_with(
        12345,
        "hello group",
        reply_to=None,
        history_message="hello group",
    )
    assert captured_extra_context["message_ids"] == ["101", "102"]
    assert captured_extra_context["batched_count"] == 2
    assert captured_extra_context["current_input_is_batched"] is True
    assert captured_resources["message_ids"] == ["101", "102"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("raw_max_tokens", "expected_max_tokens"),
    [("123", 123), (0, 0), (-5, -5), (None, 4096)],
)
async def test_execute_queued_llm_call_preserves_non_positive_max_tokens(
    raw_max_tokens: Any,
    expected_max_tokens: int,
) -> None:
    coordinator: Any = object.__new__(AICoordinator)
    model_config = SimpleNamespace(model_name="chat-model", max_tokens="4096")
    result = {"choices": [{"message": {"content": "ok"}}]}
    request_model = AsyncMock(return_value=result)
    set_llm_call_result = Mock()
    coordinator.ai = SimpleNamespace(
        request_model=request_model,
        set_llm_call_result=set_llm_call_result,
    )
    coordinator.config = SimpleNamespace(ai_request_max_retries=0)

    await BackgroundMixin._execute_queued_llm_call(
        coordinator,
        {
            "request_id": "req-1",
            "model_config": model_config,
            "messages": [{"role": "user", "content": "hello"}],
            "max_tokens": raw_max_tokens,
            "call_type": "test_call",
            "skip_prefetch_tools": True,
        },
    )

    request_model.assert_awaited_once()
    assert request_model.await_args is not None
    assert request_model.await_args.kwargs["max_tokens"] == expected_max_tokens
    assert request_model.await_args.kwargs["skip_prefetch_tools"] is True
    set_llm_call_result.assert_called_once_with("req-1", result)
