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
from Undefined.services.coordinator import AICoordinator
from Undefined.services.message_batcher import BatchDispatchToken, MessageBatcher
from Undefined.services.queue_manager import QueueManager


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
        get_context_recent_messages_limit=lambda: 20,
    )
    coordinator.ai = SimpleNamespace(attachment_registry=None)
    coordinator.security = SimpleNamespace(
        detect_injection=AsyncMock(return_value=False)
    )
    coordinator.history_manager = SimpleNamespace(
        modify_last_group_message=AsyncMock(),
        modify_last_private_message=AsyncMock(),
        get_recent_snapshot=AsyncMock(return_value=[]),
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
    assert request_data["trigger_message_id"] == 2
    assert request_data["message_ids"] == ["1", "2"]
    assert "帮我画一只猫" in request_data["full_question"]
    assert "改成狗" in request_data["full_question"]
    assert "【连续消息说明】" in request_data["full_question"]
    assert "共同构成【当前输入批次】" in request_data["full_question"]
    assert "不要把同批前几条误判为历史旧任务" in request_data["full_question"]
    assert request_data["recent_messages_snapshot"] == []


@pytest.mark.asyncio
async def test_dispatch_attaches_history_snapshot_before_enqueue() -> None:
    coordinator, qm, _ = _make_coordinator(enabled=False)
    frozen_history = [
        {
            "type": "group",
            "message_id": "100",
            "message": "发车前历史",
        }
    ]
    coordinator.history_manager.get_recent_snapshot.return_value = frozen_history

    await coordinator.handle_auto_reply(
        group_id=12345,
        sender_id=20001,
        text="当前问题",
        message_content=[],
        sender_name="user",
        group_name="测试群",
        trigger_message_id=101,
    )

    coordinator.history_manager.get_recent_snapshot.assert_awaited_once_with(
        "12345",
        "group",
        0,
        20,
    )
    await_args = cast(AsyncMock, qm.add_group_normal_request).await_args
    assert await_args is not None
    assert await_args.args[0]["recent_messages_snapshot"] == frozen_history


@pytest.mark.asyncio
async def test_each_dispatch_captures_a_fresh_history_snapshot() -> None:
    coordinator, qm, _ = _make_coordinator(enabled=False)
    coordinator.history_manager.get_recent_snapshot.side_effect = [
        [{"message_id": "100", "message": "第一轮快照"}],
        [{"message_id": "200", "message": "第二轮快照"}],
    ]

    await coordinator.handle_auto_reply(
        group_id=12345,
        sender_id=20001,
        text="第一轮",
        message_content=[],
        sender_name="user",
        group_name="测试群",
    )
    await coordinator.handle_auto_reply(
        group_id=12345,
        sender_id=20001,
        text="第二轮",
        message_content=[],
        sender_name="user",
        group_name="测试群",
    )

    assert coordinator.history_manager.get_recent_snapshot.await_count == 2
    requests = [call.args[0] for call in qm.add_group_normal_request.await_args_list]
    assert requests[0]["recent_messages_snapshot"][0]["message"] == "第一轮快照"
    assert requests[1]["recent_messages_snapshot"][0]["message"] == "第二轮快照"


@pytest.mark.asyncio
async def test_snapshot_failure_uses_authoritative_empty_history() -> None:
    coordinator, qm, _ = _make_coordinator(enabled=False)
    coordinator.history_manager.get_recent_snapshot.side_effect = RuntimeError(
        "snapshot failed"
    )

    await coordinator.handle_auto_reply(
        group_id=12345,
        sender_id=20001,
        text="当前问题",
        message_content=[],
        sender_name="user",
        group_name="测试群",
    )

    await_args = cast(AsyncMock, qm.add_group_normal_request).await_args
    assert await_args is not None
    assert await_args.args[0]["recent_messages_snapshot"] == []


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
    assert req["message_ids"] == []
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
    assert mention_req["message_ids"] == []

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
    assert req["trigger_message_id"] == 11
    assert req["message_ids"] == ["10", "11"]
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
    assert req["message_ids"] == []


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
@pytest.mark.parametrize("bypass", ["group_at", "group_poke", "private_poke"])
async def test_bypass_reply_preserves_speculative_inflight_ownership(
    bypass: str,
) -> None:
    coordinator, _mock_queue, batcher = _make_coordinator(window_seconds=60.0)
    batcher.update_config(
        MessageBatcherConfig(enabled=True, window_seconds=60.0, pre_send_seconds=10.0)
    )
    coordinator.config.bot_qq = 999
    coordinator.config.get_context_recent_messages_limit = lambda: 0
    coordinator.scheduler = None
    sent: list[str] = []

    async def send_message(_target: Any, message: str, **_kwargs: Any) -> None:
        sent.append(message)

    coordinator.sender = SimpleNamespace(
        send_group_message=send_message,
        send_address_message=send_message,
        send_private_message=AsyncMock(),
    )
    coordinator.onebot = SimpleNamespace(
        get_image=AsyncMock(), get_forward_msg=AsyncMock(), send_like=AsyncMock()
    )
    coordinator.ai.memory_storage = None
    coordinator.ai.runtime_config = coordinator.config
    started = {name: asyncio.Event() for name in ("old", "bypass", "new")}
    release = {name: asyncio.Event() for name in started}
    old_cancelled = asyncio.Event()
    finish_old_cancel = asyncio.Event()
    tasks: dict[str, asyncio.Task[Any]] = {}
    requests: dict[str, dict[str, Any]] = {}

    def request_name(question: str) -> str:
        if "独立旁路" in question:
            return "bypass"
        return "new" if "批次补充" in question else "old"

    async def ask(question: str, **kwargs: Any) -> None:
        name = request_name(question)
        current_task = asyncio.current_task()
        assert current_task is not None
        tasks[name] = current_task
        started[name].set()
        try:
            await release[name].wait()
        except asyncio.CancelledError:
            if name == "old":
                old_cancelled.set()
                # 让旧请求的 finally 在新 token 注册之后执行。
                await finish_old_cancel.wait()
            raise
        await kwargs["send_message_callback"](f"{name} reply")

    async def execute(request: dict[str, Any]) -> None:
        requests[request_name(request["full_question"])] = request
        await coordinator.execute_reply(request)

    coordinator.ai.ask = ask
    coordinator._is_at_bot = lambda content: any(
        item.get("type") == "at" for item in content
    )
    queue = QueueManager(ai_request_interval=0.0)
    coordinator.queue_manager = queue
    queue.start(execute)
    scope = "private:100" if bypass == "private_poke" else "group:1"
    key = (scope, 100)

    async def submit(text: str, *, independent: bool = False) -> None:
        if bypass == "private_poke":
            await coordinator.handle_private_reply(100, text, [], is_poke=independent)
        else:
            content = (
                [{"type": "at", "data": {"qq": "999"}}]
                if independent and bypass == "group_at"
                else []
            )
            await coordinator.handle_auto_reply(
                1,
                100,
                text,
                content,
                is_poke=independent and bypass == "group_poke",
            )

    try:
        await submit("旧批次")
        await batcher._handle_t2(key)
        await asyncio.wait_for(started["old"].wait(), timeout=1.0)
        await submit("独立旁路", independent=True)
        await asyncio.wait_for(started["bypass"].wait(), timeout=1.0)
        assert "_message_batcher_token" not in requests["bypass"]
        state = batcher._buckets[key]
        assert state.inflight is not None
        assert state.inflight.task is tasks["old"]

        await submit("批次补充")
        await asyncio.wait_for(old_cancelled.wait(), timeout=1.0)
        assert not tasks["bypass"].done()
        assert requests["old"]["_message_batcher_token"].cancelled
        await batcher._handle_t2(key)
        await asyncio.wait_for(started["new"].wait(), timeout=1.0)
        finish_old_cancel.set()
        with pytest.raises(asyncio.CancelledError):
            await tasks["old"]
        state = batcher._buckets[key]
        assert state.inflight is not None
        assert state.inflight.task is tasks["new"]

        release["bypass"].set()
        await tasks["bypass"]
        assert state.inflight is not None
        assert state.inflight.task is tasks["new"]
        release["new"].set()
        await tasks["new"]
        assert sent == ["bypass reply", "new reply"]
    finally:
        finish_old_cancel.set()
        for state in list(batcher._buckets.values()):
            batcher._cancel_t1(state)
            batcher._cancel_t2(state)
        await queue.stop()


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
    handler.pipeline_registry = SimpleNamespace(
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


@pytest.mark.asyncio
async def test_message_handler_flush_command_buffer_respects_disabled_config() -> None:
    handler: Any = object.__new__(MessageHandler)
    handler.config = SimpleNamespace(
        message_batcher=MessageBatcherConfig(flush_on_command=False)
    )
    handler.message_batcher = SimpleNamespace(flush_sender=AsyncMock(return_value=True))

    await handler._flush_command_buffer(scope="group:1", sender_id=2)

    cast(AsyncMock, handler.message_batcher.flush_sender).assert_not_called()


@pytest.mark.asyncio
async def test_message_handler_flush_command_buffer_calls_batcher_when_enabled() -> (
    None
):
    handler: Any = object.__new__(MessageHandler)
    handler.config = SimpleNamespace(
        message_batcher=MessageBatcherConfig(flush_on_command=True)
    )
    handler.message_batcher = SimpleNamespace(flush_sender=AsyncMock(return_value=True))

    await handler._flush_command_buffer(scope="group:1", sender_id=2)

    cast(AsyncMock, handler.message_batcher.flush_sender).assert_awaited_once_with(
        "group:1", 2
    )
