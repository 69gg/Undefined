"""MessageBatcher + AICoordinator 集成行为测试。

不走 handlers，直接验证：
- 同 sender 短时连续消息合并到同一队列请求；
- 队列优先级：首条 @bot 整批走 mention；buffer 已存在时新条 @bot 单独立即处理；
- 拍一拍永远旁路；
- 私聊连续合并到 add_private_request。
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

from Undefined.config.models import MessageBatcherConfig
from Undefined.handlers import MessageHandler
from Undefined.services.ai_coordinator import AICoordinator
from Undefined.services.message_batcher import BatchDispatchToken, MessageBatcher


def _make_coordinator(
    *,
    superadmin_qq: int = 99999,
    enabled: bool = True,
    window_seconds: float = 0.1,
    group_enabled: bool = True,
    private_enabled: bool = True,
) -> tuple[Any, SimpleNamespace, MessageBatcher]:
    coordinator: Any = object.__new__(AICoordinator)
    queue_manager = SimpleNamespace(
        add_group_superadmin_request=AsyncMock(),
        add_group_mention_request=AsyncMock(),
        add_group_normal_request=AsyncMock(),
        add_superadmin_request=AsyncMock(),
        add_private_request=AsyncMock(),
    )
    coordinator.config = SimpleNamespace(
        superadmin_qq=superadmin_qq,
        chat_model=SimpleNamespace(model_name="chat-model"),
    )
    coordinator.security = SimpleNamespace(
        detect_injection=AsyncMock(return_value=False)
    )
    coordinator.history_manager = SimpleNamespace(
        modify_last_group_message=AsyncMock(),
        modify_last_private_message=AsyncMock(),
    )
    coordinator.queue_manager = queue_manager
    coordinator._is_at_bot = lambda _content: False
    coordinator.model_pool = SimpleNamespace(
        select_chat_config=lambda chat_model, user_id: chat_model
    )

    cfg = MessageBatcherConfig(
        enabled=enabled,
        window_seconds=window_seconds,
        group_enabled=group_enabled,
        private_enabled=private_enabled,
    )
    batcher = MessageBatcher(cfg, coordinator.handle_batched_dispatch)
    coordinator._batcher = batcher
    return coordinator, queue_manager, batcher


@pytest.mark.asyncio
async def test_two_group_messages_merge_into_single_request() -> None:
    coordinator, qm, _ = _make_coordinator(window_seconds=0.05)

    await coordinator.handle_auto_reply(
        group_id=12345,
        sender_id=20001,
        text="帮我画一只猫",
        message_content=[],
        sender_name="user",
        group_name="测试群",
        trigger_message_id=1,
    )
    await coordinator.handle_auto_reply(
        group_id=12345,
        sender_id=20001,
        text="改成狗",
        message_content=[],
        sender_name="user",
        group_name="测试群",
        trigger_message_id=2,
    )

    # 等窗口过期 + 调度
    await asyncio.sleep(0.25)

    cast(AsyncMock, qm.add_group_normal_request).assert_awaited_once()
    cast(AsyncMock, qm.add_group_mention_request).assert_not_called()
    await_args = cast(AsyncMock, qm.add_group_normal_request).await_args
    assert await_args is not None
    request_data = await_args.args[0]
    assert request_data["batched_count"] == 2
    assert request_data["text"] == "改成狗"  # last 文本
    assert "帮我画一只猫" in request_data["full_question"]
    assert "改成狗" in request_data["full_question"]
    assert "【连续消息说明】" in request_data["full_question"]


@pytest.mark.asyncio
async def test_first_at_bot_routes_batch_to_mention_lane() -> None:
    coordinator, qm, _ = _make_coordinator(window_seconds=0.05)
    coordinator._is_at_bot = lambda content: (
        bool(content) and any(seg.get("type") == "at" for seg in content)
    )

    at_payload = [{"type": "at", "data": {"qq": "self"}}]
    await coordinator.handle_auto_reply(
        group_id=1,
        sender_id=2,
        text="@bot 帮我画猫",
        message_content=at_payload,
        sender_name="u",
        group_name="g",
    )
    await coordinator.handle_auto_reply(
        group_id=1,
        sender_id=2,
        text="改成狗",
        message_content=[],
        sender_name="u",
        group_name="g",
    )
    await asyncio.sleep(0.2)

    cast(AsyncMock, qm.add_group_mention_request).assert_awaited_once()
    cast(AsyncMock, qm.add_group_normal_request).assert_not_called()
    await_args = cast(AsyncMock, qm.add_group_mention_request).await_args
    assert await_args is not None
    req = await_args.args[0]
    assert req["batched_count"] == 2
    assert req["is_at_bot"] is True
    assert "(用户 @ 了你)" in req["full_question"]


@pytest.mark.asyncio
async def test_at_bot_arriving_with_buffer_bypasses_immediately() -> None:
    coordinator, qm, _ = _make_coordinator(window_seconds=2.0)
    is_at_calls: list[list[dict[str, Any]]] = []

    def _is_at(content: list[dict[str, Any]]) -> bool:
        is_at_calls.append(content)
        return bool(content) and any(seg.get("type") == "at" for seg in content)

    coordinator._is_at_bot = _is_at

    # 1) 普通消息进 buffer
    await coordinator.handle_auto_reply(
        group_id=1,
        sender_id=2,
        text="hi",
        message_content=[],
        sender_name="u",
        group_name="g",
    )
    # 2) 立即来一条 @bot —— 应当旁路单独立即处理
    await coordinator.handle_auto_reply(
        group_id=1,
        sender_id=2,
        text="@bot 急",
        message_content=[{"type": "at", "data": {"qq": "self"}}],
        sender_name="u",
        group_name="g",
    )

    # @bot 已立即发车
    cast(AsyncMock, qm.add_group_mention_request).assert_awaited_once()
    mention_await = cast(AsyncMock, qm.add_group_mention_request).await_args
    assert mention_await is not None
    mention_req = mention_await.args[0]
    assert mention_req["batched_count"] == 1

    # 普通桶仍未发车
    cast(AsyncMock, qm.add_group_normal_request).assert_not_called()


@pytest.mark.asyncio
async def test_poke_always_bypasses_batcher() -> None:
    coordinator, qm, _ = _make_coordinator(window_seconds=2.0)

    await coordinator.handle_auto_reply(
        group_id=1,
        sender_id=2,
        text="(拍一拍)",
        message_content=[],
        sender_name="u",
        group_name="g",
        is_poke=True,
    )

    # 拍一拍立即发车
    cast(AsyncMock, qm.add_group_mention_request).assert_awaited_once()


@pytest.mark.asyncio
async def test_private_consecutive_merge() -> None:
    coordinator, qm, _ = _make_coordinator(window_seconds=0.05)

    await coordinator.handle_private_reply(
        user_id=20001,
        text="第一条",
        message_content=[],
        sender_name="u",
        trigger_message_id=10,
    )
    await coordinator.handle_private_reply(
        user_id=20001,
        text="第二条",
        message_content=[],
        sender_name="u",
        trigger_message_id=11,
    )
    await asyncio.sleep(0.25)

    cast(AsyncMock, qm.add_private_request).assert_awaited_once()
    await_args = cast(AsyncMock, qm.add_private_request).await_args
    assert await_args is not None
    req = await_args.args[0]
    assert req["batched_count"] == 2
    assert "第一条" in req["full_question"]
    assert "第二条" in req["full_question"]


@pytest.mark.asyncio
async def test_disabled_batcher_passes_through_immediately() -> None:
    coordinator, qm, _ = _make_coordinator(enabled=False)

    await coordinator.handle_auto_reply(
        group_id=1,
        sender_id=2,
        text="hi",
        message_content=[],
        sender_name="u",
        group_name="g",
    )

    cast(AsyncMock, qm.add_group_normal_request).assert_awaited_once()


@pytest.mark.asyncio
async def test_superadmin_batched_routes_to_superadmin_lane() -> None:
    coordinator, qm, _ = _make_coordinator(superadmin_qq=10001, window_seconds=0.05)

    await coordinator.handle_auto_reply(
        group_id=1,
        sender_id=10001,
        text="hello",
        message_content=[],
        sender_name="admin",
        group_name="g",
    )
    await coordinator.handle_auto_reply(
        group_id=1,
        sender_id=10001,
        text="world",
        message_content=[],
        sender_name="admin",
        group_name="g",
    )
    await asyncio.sleep(0.25)

    cast(AsyncMock, qm.add_group_superadmin_request).assert_awaited_once()
    await_args = cast(AsyncMock, qm.add_group_superadmin_request).await_args
    assert await_args is not None
    req = await_args.args[0]
    assert req["batched_count"] == 2


@pytest.mark.asyncio
async def test_execute_reply_skips_cancelled_batch_token() -> None:
    coordinator: Any = object.__new__(AICoordinator)
    execute_auto = AsyncMock()
    coordinator._execute_auto_reply = execute_auto
    token = BatchDispatchToken(
        scope="group:1",
        sender_id=2,
        batch_id=1,
        speculative=True,
        cancelled=True,
    )

    await coordinator.execute_reply(
        {"type": "auto_reply", "_message_batcher_token": token}
    )

    execute_auto.assert_not_called()


@pytest.mark.asyncio
async def test_message_handler_close_flushes_batcher_then_drains_queue() -> None:
    handler: Any = object.__new__(MessageHandler)
    order: list[str] = []
    handler._background_tasks = set()
    handler.message_batcher = SimpleNamespace(
        flush_all=AsyncMock(side_effect=lambda: order.append("flush_batcher"))
    )
    queue_manager = SimpleNamespace(
        drain=AsyncMock(side_effect=lambda: order.append("drain_queue")),
        stop=AsyncMock(side_effect=lambda: order.append("stop_queue")),
    )
    handler.ai_coordinator = SimpleNamespace(queue_manager=queue_manager)
    handler.history_manager = SimpleNamespace(
        flush_pending_saves=AsyncMock(side_effect=lambda: order.append("flush_history"))
    )
    handler.auto_pipeline_registry = SimpleNamespace(
        stop_hot_reload=AsyncMock(side_effect=lambda: order.append("stop_pipeline"))
    )

    await handler.close()

    assert order == [
        "stop_pipeline",
        "flush_batcher",
        "drain_queue",
        "stop_queue",
        "flush_history",
    ]
