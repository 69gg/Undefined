"""Reject excess new ordinary-group LLM calls without abandoning accepted calls."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from Undefined.ai.client import AIClient
from Undefined.config import Config
from Undefined.config.hot_reload import HotReloadContext, apply_config_updates
from Undefined.config.manager import ConfigManager
from Undefined.services.queue_manager import (
    ALL_QUEUE_LANES,
    QUEUE_LANE_GROUP_NORMAL,
    QueueManager,
)


@pytest.mark.asyncio
async def test_default_group_llm_limit_rejects_only_excess_new_calls() -> None:
    queue = QueueManager()
    for index in range(128):
        await queue.add_queued_llm_request(
            {"request_id": str(index)}, lane=QUEUE_LANE_GROUP_NORMAL, model_name="chat"
        )
    with pytest.raises(asyncio.QueueFull, match="普通群聊 LLM 等待队列已满.*128"):
        await queue.add_queued_llm_request(
            {"request_id": "excess"}, lane=QUEUE_LANE_GROUP_NORMAL, model_name="chat"
        )
    assert [
        item["request_id"]
        for item in queue._model_queues["chat"].group_normal_queue.drain()
    ] == [str(index) for index in range(128)]


@pytest.mark.asyncio
@pytest.mark.parametrize("llm_type", ["queued_llm_call", "background_llm_call"])
async def test_full_llm_queue_rejects_before_trimming_outer_requests(
    llm_type: str,
) -> None:
    queue = QueueManager(group_llm_queue_max_pending=1)
    await queue.add_group_normal_request(
        {"type": llm_type, "request_id": "accepted"}, model_name="chat"
    )
    for index in range(10):
        await queue.add_group_normal_request(
            {"type": "auto_reply", "request_id": str(index)}, model_name="chat"
        )
    pending = queue._model_queues["chat"].group_normal_queue
    before = list(pending._items)
    assert len(before) == 11
    with pytest.raises(asyncio.QueueFull):
        await queue.add_group_normal_request(
            {"type": llm_type, "request_id": "excess"}, model_name="chat"
        )
    assert list(pending._items) == before


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "lane", [lane for lane in ALL_QUEUE_LANES if lane != QUEUE_LANE_GROUP_NORMAL]
)
async def test_full_group_queue_does_not_restrict_other_lane_or_model(
    lane: str,
) -> None:
    queue = QueueManager(group_llm_queue_max_pending=1)
    await queue.add_queued_llm_request(
        {}, lane=QUEUE_LANE_GROUP_NORMAL, model_name="chat"
    )
    for _ in range(2):
        await queue.add_queued_llm_request({}, lane=lane, model_name="chat")
    await queue.add_queued_llm_request(
        {}, lane=QUEUE_LANE_GROUP_NORMAL, model_name="agent"
    )
    assert queue.snapshot()["models"]["chat"][lane] == 2
    assert queue.snapshot()["models"]["agent"][QUEUE_LANE_GROUP_NORMAL] == 1


@pytest.mark.asyncio
async def test_accepted_llm_retry_can_requeue_above_new_admission_limit() -> None:
    queue = QueueManager(group_llm_queue_max_pending=1, max_retries=1)
    await queue.add_queued_llm_request(
        {"request_id": "first"}, lane=QUEUE_LANE_GROUP_NORMAL, model_name="chat"
    )
    pending = queue._model_queues["chat"].group_normal_queue
    first = pending.get_nowait()
    await queue.add_queued_llm_request(
        {"request_id": "second"}, lane=QUEUE_LANE_GROUP_NORMAL, model_name="chat"
    )

    async def fail(_request: dict[str, Any]) -> None:
        raise OSError("retryable upstream failure")

    queue.start(fail)
    await queue._safe_handle_request(first, "chat", "普通群聊")
    assert [item["request_id"] for item in pending._items] == ["second", "first"]
    assert first["_retry_count"] == 1
    with pytest.raises(asyncio.QueueFull):
        await queue.add_queued_llm_request(
            {"request_id": "third"}, lane=QUEUE_LANE_GROUP_NORMAL, model_name="chat"
        )


@pytest.mark.asyncio
async def test_submit_rejection_retires_only_the_rejected_waiter() -> None:
    queue = QueueManager(group_llm_queue_max_pending=1)
    client: Any = object.__new__(AIClient)
    client._queue_manager = queue
    client._pending_llm_calls = {}
    client._get_runtime_config = lambda: SimpleNamespace(ai_request_max_retries=0)

    async def submit() -> dict[str, Any]:
        return cast(
            dict[str, Any],
            await client.submit_queued_llm_call(
                model_config=SimpleNamespace(model_name="chat", max_tokens=64),
                messages=[{"role": "user", "content": "hello"}],
                queue_lane=QUEUE_LANE_GROUP_NORMAL,
            ),
        )

    accepted = asyncio.create_task(submit())
    try:
        await asyncio.sleep(0)
        original = dict(client._pending_llm_calls)
        assert len(original) == 1
        with pytest.raises(asyncio.QueueFull, match="请稍后重试"):
            await submit()
        assert client._pending_llm_calls == original
        assert queue.snapshot()["models"]["chat"][QUEUE_LANE_GROUP_NORMAL] == 1
    finally:
        accepted.cancel()
        await asyncio.gather(accepted, return_exceptions=True)
    assert not client._pending_llm_calls


@pytest.mark.asyncio
async def test_config_hot_reload_changes_admission_without_dropping_queued_calls(
    tmp_path: Path,
) -> None:
    path = tmp_path / "config.toml"
    path.write_text("[core]\ngroup_llm_queue_max_pending=2\n", encoding="utf-8")
    manager = ConfigManager(path)
    config = manager.load(strict=False)
    queue = QueueManager(group_llm_queue_max_pending=config.group_llm_queue_max_pending)
    context = HotReloadContext(
        ai_client=cast(Any, SimpleNamespace()),
        queue_manager=queue,
        config_manager=manager,
        security_service=cast(Any, SimpleNamespace()),
    )

    def update(updated: Config, changes: dict[str, tuple[Any, Any]]) -> None:
        apply_config_updates(updated, changes, context)

    manager.subscribe(update)
    for index in range(2):
        await queue.add_queued_llm_request(
            {"request_id": str(index)}, lane=QUEUE_LANE_GROUP_NORMAL, model_name="chat"
        )
    pending = queue._model_queues["chat"].group_normal_queue
    before = list(pending._items)
    path.write_text("[core]\ngroup_llm_queue_max_pending=1\n", encoding="utf-8")
    assert manager.reload() == {"group_llm_queue_max_pending": (2, 1)}
    assert list(pending._items) == before
    with pytest.raises(asyncio.QueueFull):
        await queue.add_queued_llm_request(
            {}, lane=QUEUE_LANE_GROUP_NORMAL, model_name="chat"
        )
    path.write_text("[core]\ngroup_llm_queue_max_pending=3\n", encoding="utf-8")
    assert manager.reload() == {"group_llm_queue_max_pending": (1, 3)}
    await queue.add_queued_llm_request(
        {"request_id": "new"}, lane=QUEUE_LANE_GROUP_NORMAL, model_name="chat"
    )
    assert list(pending._items)[:2] == before
    assert pending.qsize() == 3
    path.write_text("[core]\ngroup_llm_queue_max_pending=0\n", encoding="utf-8")
    with pytest.raises(ValueError, match="必须为正整数"):
        manager.reload()
    assert config.group_llm_queue_max_pending == 3
    assert pending.qsize() == 3
