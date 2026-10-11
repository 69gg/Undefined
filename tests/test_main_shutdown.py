from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock
import pytest

from Undefined.ai import AIClient
from Undefined.cognitive import HistorianWorker
from Undefined.handlers import MessageHandler
from Undefined.main import (
    _close_message_workers,
    _close_message_runtime,
    _run_until_shutdown,
    install_shutdown_signal_handlers,
)
from Undefined.services.queue_manager import QueueManager
from Undefined.onebot.client import OneBotClient

logger = logging.getLogger("test-main-shutdown")


@pytest.mark.asyncio
async def test_shutdown_keeps_model_queue_alive_between_historian_phases() -> None:
    queue = QueueManager(ai_request_interval=0, max_retries=0)
    ai = AIClient.__new__(AIClient)
    ai._queue_manager = queue
    ai._pending_llm_calls = {}
    ai.runtime_config = cast(Any, SimpleNamespace(ai_request_max_retries=0))
    model = SimpleNamespace(model_name="historian", max_tokens=100)
    calls: list[str] = []

    async def execute_model(request: dict[str, Any]) -> None:
        calls.append(request["call_type"])
        ai.set_llm_call_result(request["request_id"], {"ok": True})

    queue.start(execute_model)
    between_phases = asyncio.Event()
    release_io = asyncio.Event()

    async def phase() -> None:
        await ai.submit_background_llm_call(model, [], call_type="rewrite")
        between_phases.set()
        await release_io.wait()  # 向量/磁盘阶段完成后还需要一次模型调用。
        await ai.submit_background_llm_call(model, [], call_type="merge")

    worker = HistorianWorker(
        job_queue=SimpleNamespace(
            recover_stale=AsyncMock(), list_jobs=AsyncMock(return_value=[])
        ),
        vector_store=None,
        profile_storage=None,
        ai_client=ai,
        config_getter=lambda: SimpleNamespace(
            poll_interval_seconds=1, stale_job_timeout_seconds=60
        ),
    )
    await worker.start()
    phase_task = asyncio.create_task(phase())
    worker._inflight_tasks.add(phase_task)
    handler = MessageHandler.__new__(MessageHandler)
    handler._background_tasks = set()
    cast(Any, handler).pipeline_registry = SimpleNamespace(stop_hot_reload=AsyncMock())
    cast(Any, handler).ai_coordinator = SimpleNamespace(queue_manager=queue)
    flush_batches = AsyncMock()
    flush_history = AsyncMock()
    cast(Any, handler).message_batcher = SimpleNamespace(flush_all=flush_batches)
    cast(Any, handler).history_manager = SimpleNamespace(
        flush_pending_saves=flush_history
    )
    meme = SimpleNamespace(stop=AsyncMock())
    close_task: asyncio.Task[None] | None = None
    try:
        await asyncio.wait_for(between_phases.wait(), timeout=2)
        close_task = asyncio.create_task(
            _close_message_workers(
                handler,
                meme_worker=cast(Any, meme),
                historian_worker=worker,
                logger=logger,
            )
        )
        await asyncio.sleep(0)
        assert not close_task.done()
        assert queue._processor_tasks
        assert calls == ["rewrite"]
        flush_batches.assert_not_awaited()
        release_io.set()
        await asyncio.wait_for(close_task, timeout=2)
        assert calls == ["rewrite", "merge"]
        assert not ai._pending_llm_calls
        assert not queue._processor_tasks
        meme.stop.assert_awaited_once()
        flush_history.assert_awaited_once()
    finally:
        release_io.set()
        phase_task.cancel()
        if close_task is not None:
            close_task.cancel()
            await asyncio.gather(close_task, return_exceptions=True)
        await asyncio.gather(phase_task, return_exceptions=True)
        await worker.stop()
        await queue.stop()


class _SlowOneBot:
    def __init__(self) -> None:
        self.cancelled = False

    async def run_with_reconnect(self) -> None:
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            self.cancelled = True
            raise


class _FailingOneBot:
    async def run_with_reconnect(self) -> None:
        raise RuntimeError("connection boom")


@pytest.mark.asyncio
async def test_run_until_shutdown_keeps_onebot_alive_for_drain() -> None:
    onebot = _SlowOneBot()
    shutdown_event = asyncio.Event()

    task = asyncio.create_task(
        _run_until_shutdown(onebot, shutdown_event, logger)  # type: ignore[arg-type]
    )
    await asyncio.sleep(0.05)
    shutdown_event.set()
    connection = await asyncio.wait_for(task, timeout=2)
    assert onebot.cancelled is False
    assert not connection.done()
    connection.cancel()
    await asyncio.gather(connection, return_exceptions=True)
    assert onebot.cancelled is True


class _ReplyWebSocket:
    close_code: int | None = None

    def __init__(self) -> None:
        self.frames: asyncio.Queue[str] = asyncio.Queue()
        self.receiving = asyncio.Event()
        self.sent: list[dict[str, Any]] = []

    async def recv(self) -> str:
        self.receiving.set()
        return await self.frames.get()

    async def send(self, payload: str) -> None:
        request = json.loads(payload)
        self.sent.append(request)
        await self.frames.put(json.dumps({"echo": request["echo"], "status": "ok"}))

    async def close(self) -> None:
        self.close_code = 1000
        await self.frames.put("{}")


@pytest.mark.asyncio
async def test_shutdown_finishes_accepted_reply_before_closing_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    onebot = OneBotClient("ws://isolated.invalid")
    socket = _ReplyWebSocket()
    onebot.ws = cast(Any, socket)
    monkeypatch.setattr(onebot, "connect", AsyncMock())
    shutdown = asyncio.Event()
    wait_task = asyncio.create_task(_run_until_shutdown(onebot, shutdown, logger))
    await asyncio.wait_for(socket.receiving.wait(), 1)
    queue = QueueManager(ai_request_interval=0, max_retries=0)
    reply_started = asyncio.Event()
    release_reply = asyncio.Event()
    order: list[str] = []

    async def reply(request: dict[str, Any]) -> None:
        reply_started.set()
        await release_reply.wait()
        response = await onebot.send_group_message(1, "accepted reply")
        assert response["status"] == "ok"
        order.append("delivered")

    calls: list[str] = []

    async def inbound(data: dict[str, Any]) -> None:
        calls.append("accepted")
        await queue.add_private_request({"type": "private_reply"})

    queue.start(reply)
    onebot.set_message_handler(inbound)
    await onebot._dispatch_message({"post_type": "message"})
    await asyncio.wait_for(reply_started.wait(), 1)
    handler = MessageHandler.__new__(MessageHandler)
    handler._background_tasks = set()
    cast(Any, handler).pipeline_registry = SimpleNamespace(stop_hot_reload=AsyncMock())
    cast(Any, handler).ai_coordinator = SimpleNamespace(queue_manager=queue)
    cast(Any, handler).message_batcher = SimpleNamespace(flush_all=AsyncMock())

    async def flush() -> None:
        order.append("history")

    cast(Any, handler).history_manager = SimpleNamespace(flush_pending_saves=flush)
    shutdown.set()
    connection = await asyncio.wait_for(wait_task, 1)
    close_task = asyncio.create_task(
        _close_message_runtime(
            onebot,
            handler,
            runtime_api_server=None,
            weixin_service=None,
            meme_worker=None,
            historian_worker=None,
            logger=logger,
        )
    )
    try:
        await asyncio.sleep(0)
        assert onebot._running
        assert not close_task.done()
        await onebot._dispatch_message({"post_type": "message"})
        await onebot._dispatch_message(
            {"post_type": "notice", "notice_type": "notify", "sub_type": "poke"}
        )
        assert calls == ["accepted"]
        release_reply.set()
        await asyncio.wait_for(close_task, 2)
        await asyncio.wait_for(connection, 1)
        assert order == ["delivered", "history"]
        assert len(socket.sent) == 1
        assert socket.frames.empty()
    finally:
        release_reply.set()
        close_task.cancel()
        connection.cancel()
        await asyncio.gather(close_task, connection, return_exceptions=True)
        await queue.stop()


@pytest.mark.asyncio
async def test_run_until_shutdown_propagates_connection_error() -> None:
    with pytest.raises(RuntimeError, match="connection boom"):
        await _run_until_shutdown(
            _FailingOneBot(),  # type: ignore[arg-type]
            asyncio.Event(),
            logger,
        )


@pytest.mark.asyncio
async def test_install_shutdown_signal_handlers_reacts_to_sigterm() -> None:
    if not hasattr(signal, "SIGTERM"):  # pragma: no cover - 非 POSIX 平台
        pytest.skip("SIGTERM unavailable")

    original = signal.getsignal(signal.SIGTERM)
    guard = install_shutdown_signal_handlers(logger)
    if signal.getsignal(signal.SIGTERM) is signal.SIG_DFL:
        pytest.skip("当前事件循环不支持信号处理器")
    try:
        os.kill(os.getpid(), signal.SIGTERM)
        await asyncio.wait_for(guard.event.wait(), timeout=2)
        assert guard.event.is_set()
    finally:
        guard.restore()
    assert signal.getsignal(signal.SIGTERM) is original


@pytest.mark.asyncio
async def test_install_shutdown_signal_handlers_restore_returns_previous_handler() -> (
    None
):
    if not hasattr(signal, "SIGTERM"):  # pragma: no cover - 非 POSIX 平台
        pytest.skip("SIGTERM unavailable")

    def _previous_handler(signum: object, frame: object) -> None:  # pragma: no cover
        return None

    original = signal.signal(signal.SIGTERM, _previous_handler)
    try:
        guard = install_shutdown_signal_handlers(logger)
        guard.restore()
        assert signal.getsignal(signal.SIGTERM) is _previous_handler
    finally:
        signal.signal(signal.SIGTERM, original)


@pytest.mark.asyncio
async def test_install_shutdown_signal_handlers_restore_is_idempotent() -> None:
    if not hasattr(signal, "SIGTERM"):  # pragma: no cover - 非 POSIX 平台
        pytest.skip("SIGTERM unavailable")

    original = signal.getsignal(signal.SIGTERM)
    guard = install_shutdown_signal_handlers(logger)
    guard.restore()
    # 二次调用为空操作：previous 已清空，不得抛错或再改信号状态
    guard.restore()
    assert signal.getsignal(signal.SIGTERM) is original


@pytest.mark.asyncio
async def test_install_shutdown_signal_handlers_returns_fresh_event() -> None:
    guard = install_shutdown_signal_handlers(logger)
    assert isinstance(guard.event, asyncio.Event)
    assert guard.event.is_set() is False
    guard.restore()
