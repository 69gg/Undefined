"""MessageBatcher 单元测试。"""

from __future__ import annotations

import asyncio
import time

import pytest

from Undefined.config.models import MessageBatcherConfig
from Undefined.services.message_batcher import (
    BufferedMessage,
    MessageBatcher,
    make_scope,
)


def _make_item(
    *,
    scope: str = "group:1",
    sender_id: int = 100,
    text: str = "hi",
    is_private: bool = False,
    is_poke: bool = False,
    is_at_bot: bool = False,
    sender_name: str = "test",
) -> BufferedMessage:
    return BufferedMessage(
        scope=scope,
        sender_id=sender_id,
        text=text,
        message_content=[{"type": "text", "data": {"text": text}}],
        attachments=[],
        sender_name=sender_name,
        arrival_time=time.time(),
        is_private=is_private,
        trigger_message_id=1,
        is_poke=is_poke,
        is_at_bot=is_at_bot,
        group_id=None if is_private else 1,
    )


class _Recorder:
    def __init__(self) -> None:
        self.batches: list[list[BufferedMessage]] = []
        self.event = asyncio.Event()

    async def __call__(self, items: list[BufferedMessage]) -> None:
        self.batches.append(items)
        self.event.set()


def test_make_scope() -> None:
    assert make_scope(group_id=10) == "group:10"
    assert make_scope(user_id=5) == "private:5"
    assert make_scope() == "unknown"


@pytest.mark.asyncio
async def test_consecutive_same_sender_merge() -> None:
    cfg = MessageBatcherConfig(enabled=True, window_seconds=0.1, strategy="extend")
    rec = _Recorder()
    batcher = MessageBatcher(cfg, rec)

    await batcher.submit(_make_item(text="msg1"))
    await batcher.submit(_make_item(text="msg2"))
    await batcher.submit(_make_item(text="msg3"))

    await asyncio.wait_for(rec.event.wait(), timeout=1.0)
    assert len(rec.batches) == 1
    assert [m.text for m in rec.batches[0]] == ["msg1", "msg2", "msg3"]


@pytest.mark.asyncio
async def test_different_senders_isolated() -> None:
    cfg = MessageBatcherConfig(enabled=True, window_seconds=0.1)
    rec = _Recorder()
    batcher = MessageBatcher(cfg, rec)

    await batcher.submit(_make_item(sender_id=1, text="a"))
    await batcher.submit(_make_item(sender_id=2, text="b"))

    await asyncio.sleep(0.3)
    assert len(rec.batches) == 2
    flat = sorted([b[0].sender_id for b in rec.batches])
    assert flat == [1, 2]


@pytest.mark.asyncio
async def test_max_messages_immediate_flush() -> None:
    cfg = MessageBatcherConfig(
        enabled=True,
        window_seconds=10.0,
        max_messages_per_batch=2,
    )
    rec = _Recorder()
    batcher = MessageBatcher(cfg, rec)

    await batcher.submit(_make_item(text="x"))
    await batcher.submit(_make_item(text="y"))

    # 立即发车，不需要等窗口
    assert len(rec.batches) == 1
    assert len(rec.batches[0]) == 2


@pytest.mark.asyncio
async def test_max_window_hard_cap() -> None:
    cfg = MessageBatcherConfig(
        enabled=True,
        window_seconds=0.05,
        strategy="extend",
        max_window_seconds=0.15,
    )
    rec = _Recorder()
    batcher = MessageBatcher(cfg, rec)

    # 持续提交,extend 应被 max_window 硬顶
    for _ in range(10):
        await batcher.submit(_make_item(text="x"))
        await asyncio.sleep(0.03)

    await asyncio.sleep(0.3)
    # 至少触发过一次 flush
    assert len(rec.batches) >= 1


@pytest.mark.asyncio
async def test_disabled_means_caller_should_bypass() -> None:
    cfg = MessageBatcherConfig(enabled=False, window_seconds=0.1)
    rec = _Recorder()
    batcher = MessageBatcher(cfg, rec)

    assert batcher.is_enabled_for(is_group=True) is False
    assert batcher.is_enabled_for(is_group=False) is False


@pytest.mark.asyncio
async def test_group_only_disabled() -> None:
    cfg = MessageBatcherConfig(
        enabled=True, window_seconds=0.1, group_enabled=False, private_enabled=True
    )
    batcher = MessageBatcher(cfg, lambda items: asyncio.sleep(0))
    assert batcher.is_enabled_for(is_group=True) is False
    assert batcher.is_enabled_for(is_group=False) is True


@pytest.mark.asyncio
async def test_has_buffer() -> None:
    cfg = MessageBatcherConfig(enabled=True, window_seconds=10.0)
    rec = _Recorder()
    batcher = MessageBatcher(cfg, rec)

    assert not batcher.has_buffer("group:1", 100)
    await batcher.submit(_make_item())
    assert batcher.has_buffer("group:1", 100)


@pytest.mark.asyncio
async def test_flush_all_on_shutdown() -> None:
    cfg = MessageBatcherConfig(enabled=True, window_seconds=10.0)
    rec = _Recorder()
    batcher = MessageBatcher(cfg, rec)

    await batcher.submit(_make_item(sender_id=1, text="a"))
    await batcher.submit(_make_item(sender_id=2, text="b"))
    assert len(rec.batches) == 0

    await batcher.flush_all()
    assert len(rec.batches) == 2


@pytest.mark.asyncio
async def test_extend_resets_timer() -> None:
    cfg = MessageBatcherConfig(enabled=True, window_seconds=0.15, strategy="extend")
    rec = _Recorder()
    batcher = MessageBatcher(cfg, rec)

    await batcher.submit(_make_item(text="a"))
    await asyncio.sleep(0.10)
    await batcher.submit(_make_item(text="b"))
    await asyncio.sleep(0.10)
    # 这个时间点本来 a 已经超过初始 0.15s 窗口；若 extend 重置则 b 还在等
    assert len(rec.batches) == 0
    await asyncio.sleep(0.20)
    assert len(rec.batches) == 1


@pytest.mark.asyncio
async def test_fixed_does_not_reset_timer() -> None:
    cfg = MessageBatcherConfig(enabled=True, window_seconds=0.15, strategy="fixed")
    rec = _Recorder()
    batcher = MessageBatcher(cfg, rec)

    await batcher.submit(_make_item(text="a"))
    await asyncio.sleep(0.05)
    await batcher.submit(_make_item(text="b"))
    # fixed 策略下定时器从首条算起,大约 0.15s 后 flush
    await asyncio.sleep(0.20)
    assert len(rec.batches) == 1
    assert len(rec.batches[0]) == 2


@pytest.mark.asyncio
async def test_update_config_runtime() -> None:
    cfg = MessageBatcherConfig(enabled=True, window_seconds=0.1)
    rec = _Recorder()
    batcher = MessageBatcher(cfg, rec)

    new_cfg = MessageBatcherConfig(enabled=False, window_seconds=0.5)
    batcher.update_config(new_cfg)
    assert batcher.config.enabled is False
    assert batcher.is_enabled_for(is_group=True) is False


@pytest.mark.asyncio
async def test_callback_exception_does_not_break_batcher() -> None:
    cfg = MessageBatcherConfig(enabled=True, window_seconds=0.05)

    calls: list[int] = []

    async def bad_callback(items: list[BufferedMessage]) -> None:
        calls.append(len(items))
        raise RuntimeError("boom")

    batcher = MessageBatcher(cfg, bad_callback)
    await batcher.submit(_make_item(text="a"))
    await asyncio.sleep(0.2)
    assert calls == [1]

    # 应能继续接受新消息
    await batcher.submit(_make_item(text="b"))
    await asyncio.sleep(0.2)
    assert calls == [1, 1]


@pytest.mark.asyncio
async def test_timer_task_strong_reference_survives_gc() -> None:
    """timer 触发后创建的 flush task 必须被强引用，避免被 GC 回收。

    asyncio 文档明确警告 ``create_task`` 返回值若不被保留，可能在执行前被 GC。
    """
    import gc

    cfg = MessageBatcherConfig(enabled=True, window_seconds=0.05, strategy="extend")
    rec = _Recorder()
    batcher = MessageBatcher(cfg, rec)

    await batcher.submit(_make_item(text="x"))
    # 在 timer 触发后但 callback 未必完成时强制 GC
    await asyncio.sleep(0.06)
    gc.collect()
    await asyncio.wait_for(rec.event.wait(), timeout=1.0)
    assert len(rec.batches) == 1


@pytest.mark.asyncio
async def test_flush_all_awaits_in_flight_tasks() -> None:
    """flush_all 应等待 timer 触发但 callback 仍在执行的 task 收尾。"""
    cfg = MessageBatcherConfig(enabled=True, window_seconds=0.05)
    finished: list[bool] = []
    started = asyncio.Event()

    async def slow_callback(items: list[BufferedMessage]) -> None:
        started.set()
        await asyncio.sleep(0.15)
        finished.append(True)

    batcher = MessageBatcher(cfg, slow_callback)
    await batcher.submit(_make_item(text="x"))
    # 等 timer 触发并进入 callback
    await asyncio.wait_for(started.wait(), timeout=1.0)
    # callback 仍在 sleep 中调 flush_all 应阻塞直到完成
    await batcher.flush_all()
    assert finished == [True]


@pytest.mark.asyncio
async def test_max_window_seconds_zero_means_unlimited() -> None:
    """max_window_seconds=0 表示不限制硬顶，只要 extend 持续刷新就一直等。"""
    cfg = MessageBatcherConfig(
        enabled=True,
        window_seconds=0.05,
        strategy="extend",
        max_window_seconds=0.0,
    )
    rec = _Recorder()
    batcher = MessageBatcher(cfg, rec)

    # 连续 6 次提交，每次间隔 30ms（< window_seconds），如果 max_window 仍生效会被强行 flush
    for i in range(6):
        await batcher.submit(_make_item(text=f"m{i}"))
        await asyncio.sleep(0.03)
    # 此时距首条已 ~180ms（远超旧 max_window 的虚假"硬顶"，但 0=不限），仍应在 buffer 中
    assert rec.batches == []
    # 停止追加，让 timer 自然到期
    await asyncio.sleep(0.1)
    assert len(rec.batches) == 1
    assert len(rec.batches[0]) == 6


# ---------------------------------------------------------------------------
# 投机预发送（speculative pre-fire）测试
# ---------------------------------------------------------------------------


class _FakeRequestContext:
    """模拟 RequestContext，仅暴露 get_resource。"""

    def __init__(self) -> None:
        self._resources: dict[str, object] = {}

    def set_resource(self, key: str, value: object) -> None:
        self._resources[key] = value

    def get_resource(self, key: str, default: object = None) -> object:
        return self._resources.get(key, default)


@pytest.mark.asyncio
async def test_speculative_prefire_fires_at_t2_but_batch_continues() -> None:
    """T2 < T1：T2 到期先发车，items 不弹出；T1 之前再来消息会取消投机。"""
    cfg = MessageBatcherConfig(
        enabled=True,
        window_seconds=0.3,
        pre_send_seconds=0.1,
        strategy="extend",
    )
    rec = _Recorder()
    batcher = MessageBatcher(cfg, rec)

    await batcher.submit(_make_item(text="m1"))
    # 等待 T2 触发（~100ms）但远未到 T1（300ms）
    await asyncio.sleep(0.18)
    assert len(rec.batches) == 1, "T2 应已 pre-fire"
    # 桶仍存在
    assert batcher.has_buffer("group:1", 100)


@pytest.mark.asyncio
async def test_speculative_cancelled_when_new_message_and_no_send() -> None:
    """投机调用尚未发出消息时，新消息到达应取消 inflight 并把它合进新一轮。"""
    cfg = MessageBatcherConfig(
        enabled=True,
        window_seconds=0.3,
        pre_send_seconds=0.05,
        strategy="extend",
    )

    cancelled = asyncio.Event()
    fake_ctx = _FakeRequestContext()  # 默认 message_sent_this_turn=False

    async def slow_flush(items: list[BufferedMessage]) -> None:
        try:
            await asyncio.sleep(2.0)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    batcher = MessageBatcher(cfg, slow_flush)

    await batcher.submit(_make_item(text="m1"))
    # 等待 T2 触发
    await asyncio.sleep(0.1)
    # 模拟 coordinator 上报 inflight
    inflight_task = next(iter(batcher._pending_tasks))
    batcher.register_inflight("group:1", 100, inflight_task, fake_ctx)
    # 第二条消息到达，应取消 inflight
    await batcher.submit(_make_item(text="m2"))
    await asyncio.wait_for(cancelled.wait(), timeout=1.0)


@pytest.mark.asyncio
async def test_speculative_not_cancelled_when_already_sent_default() -> None:
    """已经发过消息时默认不取消 inflight，新消息开新 batch。"""
    cfg = MessageBatcherConfig(
        enabled=True,
        window_seconds=0.3,
        pre_send_seconds=0.05,
        strategy="extend",
        allow_cancel_after_send=False,
    )

    fake_ctx = _FakeRequestContext()
    fake_ctx.set_resource("message_sent_this_turn", True)

    finished = asyncio.Event()

    async def flush(items: list[BufferedMessage]) -> None:
        try:
            await asyncio.sleep(0.1)
        finally:
            finished.set()

    batcher = MessageBatcher(cfg, flush)

    await batcher.submit(_make_item(text="m1"))
    await asyncio.sleep(0.08)
    inflight_task = next(iter(batcher._pending_tasks))
    batcher.register_inflight("group:1", 100, inflight_task, fake_ctx)
    # 新消息到达：投机已发过消息，inflight 不应被 cancel
    await batcher.submit(_make_item(text="m2"))
    # 等 inflight 自然完成
    await asyncio.wait_for(finished.wait(), timeout=1.0)
    assert not inflight_task.cancelled()


@pytest.mark.asyncio
async def test_speculative_disabled_when_pre_send_zero() -> None:
    """pre_send_seconds=0 时投机关闭，仅 T1 静默到期发车。"""
    cfg = MessageBatcherConfig(
        enabled=True,
        window_seconds=0.1,
        pre_send_seconds=0.0,
    )
    rec = _Recorder()
    batcher = MessageBatcher(cfg, rec)
    assert not batcher.speculative_enabled

    await batcher.submit(_make_item(text="m1"))
    await asyncio.sleep(0.05)
    assert rec.batches == []
    await asyncio.sleep(0.1)
    assert len(rec.batches) == 1


@pytest.mark.asyncio
async def test_snapshot_includes_phase() -> None:
    cfg = MessageBatcherConfig(enabled=True, window_seconds=0.5, pre_send_seconds=0.05)
    rec = _Recorder()
    batcher = MessageBatcher(cfg, rec)
    await batcher.submit(_make_item(text="m1"))
    snap = batcher.snapshot()
    assert snap["pending_buckets"] == 1
    assert snap["buckets"][0]["phase"] in {"typing", "speculating"}
    assert "speculative_enabled" in snap["config"]
    assert snap["config"]["speculative_enabled"] is True
