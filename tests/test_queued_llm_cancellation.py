"""Caller cancellation propagates through queued LLM execution and retries."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from Undefined.ai.client import AIClient
from Undefined.ai.client import queue as queue_module
from Undefined.services.coordinator.background import BackgroundMixin


class _CapturingQueue:
    def __init__(self) -> None:
        self.enqueued = asyncio.Event()
        self.request: dict[str, Any] = {}

    def get_max_retries(self) -> int:
        return 1

    async def add_queued_llm_request(
        self, request: dict[str, Any], **kwargs: Any
    ) -> SimpleNamespace:
        self.request = dict(request)
        self.enqueued.set()
        return SimpleNamespace(estimated_wait_seconds=0)


def _client_and_coordinator() -> tuple[Any, Any, _CapturingQueue]:
    queue = _CapturingQueue()
    client: Any = object.__new__(AIClient)
    client._queue_manager = queue
    client._pending_llm_calls = {}
    client._get_runtime_config = lambda: SimpleNamespace(ai_request_max_retries=1)
    client.request_model = AsyncMock(return_value={"choices": []})
    coordinator: Any = object.__new__(BackgroundMixin)
    coordinator.ai = client
    coordinator.config = SimpleNamespace(ai_request_max_retries=1)
    coordinator.queue_manager = queue
    return client, coordinator, queue


def _submit(client: Any) -> asyncio.Task[dict[str, Any]]:
    return asyncio.create_task(
        client.submit_queued_llm_call(
            model_config=SimpleNamespace(model_name="chat", max_tokens=64),
            messages=[{"role": "user", "content": "hello"}],
            queue_lane="background",
        )
    )


def _zero_timeout(*args: Any, **kwargs: Any) -> float:
    return 0.0


@pytest.mark.asyncio
@pytest.mark.parametrize("timeout", [False, True])
async def test_cancelled_waiter_is_skipped_before_model_dispatch(
    monkeypatch: pytest.MonkeyPatch, timeout: bool
) -> None:
    client, coordinator, queue = _client_and_coordinator()
    if timeout:
        monkeypatch.setattr(
            queue_module, "compute_queued_llm_timeout_seconds", _zero_timeout
        )
    caller = _submit(client)
    await asyncio.wait_for(queue.enqueued.wait(), 1)
    if not timeout:
        caller.cancel()
    with pytest.raises(TimeoutError if timeout else asyncio.CancelledError):
        await caller
    await coordinator._execute_queued_llm_call(queue.request)
    client.request_model.assert_not_awaited()
    assert not client._pending_llm_calls


@pytest.mark.asyncio
async def test_caller_cancellation_stops_active_model_task() -> None:
    client, coordinator, queue = _client_and_coordinator()
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def request_model(**kwargs: Any) -> dict[str, Any]:
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()
        return {}

    client.request_model = AsyncMock(side_effect=request_model)
    caller = _submit(client)
    await asyncio.wait_for(queue.enqueued.wait(), 1)
    dispatch = asyncio.create_task(coordinator._execute_queued_llm_call(queue.request))
    await asyncio.wait_for(started.wait(), 1)
    caller.cancel()
    with pytest.raises(asyncio.CancelledError):
        await caller
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(dispatch, 1)
    assert cancelled.is_set()
    assert not client._pending_llm_calls


@pytest.mark.asyncio
async def test_cancelled_waiter_is_not_called_again_after_retryable_failure() -> None:
    client, coordinator, queue = _client_and_coordinator()
    client.request_model = AsyncMock(side_effect=RuntimeError("retryable"))
    caller = _submit(client)
    await asyncio.wait_for(queue.enqueued.wait(), 1)
    with pytest.raises(RuntimeError, match="retryable"):
        await coordinator._execute_queued_llm_call(queue.request)
    assert not caller.done()
    caller.cancel()
    with pytest.raises(asyncio.CancelledError):
        await caller
    await coordinator._execute_queued_llm_call({**queue.request, "_retry_count": 1})
    client.request_model.assert_awaited_once()


@pytest.mark.asyncio
async def test_uncancelled_queued_call_delivers_its_result() -> None:
    client, coordinator, queue = _client_and_coordinator()
    caller = _submit(client)
    await asyncio.wait_for(queue.enqueued.wait(), 1)
    await coordinator._execute_queued_llm_call(queue.request)
    assert await asyncio.wait_for(caller, 1) == {"choices": []}
    client.request_model.assert_awaited_once()
    assert not client._pending_llm_calls
