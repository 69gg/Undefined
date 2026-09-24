from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest

from Undefined.services.coordinator.background import BackgroundMixin
from Undefined.services.queue_manager import QUEUE_LANE_BACKGROUND


def _make_coordinator(
    *,
    queue_max_retries: int | None,
    config_max_retries: int,
) -> Any:
    coordinator: Any = object.__new__(BackgroundMixin)
    coordinator.config = SimpleNamespace(
        ai_request_max_retries=config_max_retries,
    )
    if queue_max_retries is None:
        queue_manager = SimpleNamespace()
    else:
        queue_manager = SimpleNamespace(
            get_max_retries=Mock(return_value=queue_max_retries)
        )
    coordinator.queue_manager = queue_manager
    ai = SimpleNamespace()
    ai.request_model = AsyncMock(side_effect=RuntimeError("llm boom"))
    ai.set_llm_call_result = Mock()
    coordinator.ai = ai
    return coordinator


def _request(retry_count: int) -> dict[str, Any]:
    return {
        "type": "queued_llm_call",
        "request_id": "req-1",
        "model_config": SimpleNamespace(model_name="chat", max_tokens=64),
        "messages": [{"role": "user", "content": "hi"}],
        "call_type": "background",
        "_retry_count": retry_count,
        "_queue_lane": QUEUE_LANE_BACKGROUND,
    }


@pytest.mark.asyncio
async def test_waiter_keeps_waiting_when_queue_can_still_retry() -> None:
    """队列上限大于 config 时，不应过早把失败交给等待方。"""
    coordinator = _make_coordinator(queue_max_retries=3, config_max_retries=0)

    with pytest.raises(RuntimeError, match="llm boom"):
        await coordinator._execute_queued_llm_call(_request(retry_count=0))

    coordinator.ai.set_llm_call_result.assert_not_called()


@pytest.mark.asyncio
async def test_waiter_released_when_queue_retries_exhausted() -> None:
    """重试已耗尽时必须立刻唤醒等待方，而不是挂到 480s 超时。"""
    coordinator = _make_coordinator(queue_max_retries=3, config_max_retries=9)

    with pytest.raises(RuntimeError, match="llm boom"):
        await coordinator._execute_queued_llm_call(_request(retry_count=3))

    coordinator.ai.set_llm_call_result.assert_called_once()
    assert coordinator.ai.set_llm_call_result.call_args.args[0] == "req-1"
    assert isinstance(
        coordinator.ai.set_llm_call_result.call_args.args[1], RuntimeError
    )


@pytest.mark.asyncio
async def test_config_retries_used_when_queue_manager_missing_limit() -> None:
    coordinator = _make_coordinator(queue_max_retries=None, config_max_retries=2)

    with pytest.raises(RuntimeError):
        await coordinator._execute_queued_llm_call(_request(retry_count=1))
    coordinator.ai.set_llm_call_result.assert_not_called()

    coordinator = _make_coordinator(queue_max_retries=None, config_max_retries=2)
    with pytest.raises(RuntimeError):
        await coordinator._execute_queued_llm_call(_request(retry_count=2))
    coordinator.ai.set_llm_call_result.assert_called_once()


@pytest.mark.asyncio
async def test_zero_retry_limit_releases_immediately() -> None:
    coordinator = _make_coordinator(queue_max_retries=0, config_max_retries=5)

    with pytest.raises(RuntimeError):
        await coordinator._execute_queued_llm_call(_request(retry_count=0))

    coordinator.ai.set_llm_call_result.assert_called_once()
