from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from Undefined.config.loader import Config
from Undefined.services.queue_manager import (
    QUEUE_LANE_BACKGROUND,
    QUEUE_LANE_PRIVATE,
    QueueManager,
)


def _load_config(path: Path, text: str) -> Config:
    path.write_text(text, "utf-8")
    return Config.load(path, strict=False)


@pytest.mark.asyncio
async def test_group_superadmin_is_prioritized_after_superadmin() -> None:
    order: list[str] = []
    processed = asyncio.Event()

    queue_manager = QueueManager(ai_request_interval=0.0)
    await queue_manager.add_private_request(
        {"type": "private_reply", "request_id": "private"},
        model_name="chat-model",
    )
    await queue_manager.add_group_superadmin_request(
        {"type": "auto_reply", "request_id": "group-superadmin"},
        model_name="chat-model",
    )
    await queue_manager.add_superadmin_request(
        {"type": "private_reply", "request_id": "superadmin"},
        model_name="chat-model",
    )

    async def _handler(request: dict[str, Any]) -> None:
        order.append(str(request["request_id"]))
        if len(order) >= 3:
            processed.set()

    queue_manager.start(_handler)
    queue_manager._processor_tasks["chat-model"] = asyncio.create_task(
        queue_manager._process_model_loop("chat-model")
    )

    try:
        await asyncio.wait_for(processed.wait(), timeout=1.0)
    finally:
        await queue_manager.stop()

    assert order[:3] == ["superadmin", "group-superadmin", "private"]


@pytest.mark.asyncio
async def test_queued_llm_request_requeues_to_second_position() -> None:
    attempts: dict[str, int] = {"first": 0}

    queue_manager = QueueManager(max_retries=2)
    request_template = {
        "model_config": SimpleNamespace(model_name="chat-model", max_tokens=128),
        "messages": [{"role": "user", "content": "hello"}],
        "call_type": "chat",
    }
    await queue_manager.add_queued_llm_request(
        {"request_id": "first", **request_template},
        lane=QUEUE_LANE_PRIVATE,
        model_name="chat-model",
    )
    await queue_manager.add_queued_llm_request(
        {"request_id": "second", **request_template},
        lane=QUEUE_LANE_PRIVATE,
        model_name="chat-model",
    )
    await queue_manager.add_queued_llm_request(
        {"request_id": "third", **request_template},
        lane=QUEUE_LANE_PRIVATE,
        model_name="chat-model",
    )

    async def _handler(request: dict[str, Any]) -> None:
        request_id = str(request["request_id"])
        if request_id == "first" and attempts["first"] == 0:
            attempts["first"] += 1
            raise RuntimeError("boom")

    queue_manager.start(_handler)
    model_queue = queue_manager._model_queues["chat-model"]
    first_request = model_queue.private_queue.get_nowait()

    await queue_manager._safe_handle_request(first_request, "chat-model", "普通私聊")

    remaining_ids = [item["request_id"] for item in model_queue.private_queue.drain()]
    assert first_request["_retry_count"] == 1
    assert remaining_ids == ["second", "first", "third"]


@pytest.mark.asyncio
async def test_enqueue_receipt_counts_remaining_current_dispatch_interval() -> None:
    queue_manager = QueueManager(ai_request_interval=0.2)
    first_dispatched = asyncio.Event()
    release_first = asyncio.Event()

    async def _handler(request: dict[str, Any]) -> None:
        if request["request_id"] == "first":
            first_dispatched.set()
            await release_first.wait()

    queue_manager.start(_handler)
    await queue_manager.add_queued_llm_request(
        {
            "request_id": "first",
            "model_config": SimpleNamespace(model_name="chat-model", max_tokens=128),
            "messages": [{"role": "user", "content": "hello"}],
            "call_type": "chat",
        },
        lane=QUEUE_LANE_PRIVATE,
        model_name="chat-model",
    )
    queue_manager._processor_tasks["chat-model"] = asyncio.create_task(
        queue_manager._process_model_loop("chat-model")
    )

    try:
        await asyncio.wait_for(first_dispatched.wait(), timeout=1.0)
        receipt = await queue_manager.add_queued_llm_request(
            {
                "request_id": "second",
                "model_config": SimpleNamespace(
                    model_name="chat-model", max_tokens=128
                ),
                "messages": [{"role": "user", "content": "hello"}],
                "call_type": "chat",
            },
            lane=QUEUE_LANE_PRIVATE,
            model_name="chat-model",
        )
        assert receipt.estimated_wait_seconds > 0.0
    finally:
        release_first.set()
        await queue_manager.stop()


@pytest.mark.asyncio
async def test_non_llm_request_failure_is_not_retried_and_snapshot_counts_retry() -> (
    None
):
    queue_manager = QueueManager(max_retries=3)
    await queue_manager.add_private_request(
        {"type": "private_reply", "request_id": "private"},
        model_name="chat-model",
    )
    await queue_manager.add_queued_llm_request(
        {
            "request_id": "queued-retry",
            "_retry_count": 1,
            "model_config": SimpleNamespace(model_name="chat-model", max_tokens=128),
            "messages": [{"role": "user", "content": "hello"}],
            "call_type": "chat",
        },
        lane=QUEUE_LANE_BACKGROUND,
        model_name="chat-model",
    )

    async def _handler(_: dict[str, Any]) -> None:
        raise RuntimeError("fail")

    queue_manager.start(_handler)
    model_queue = queue_manager._model_queues["chat-model"]
    private_request = model_queue.private_queue.get_nowait()

    await queue_manager._safe_handle_request(private_request, "chat-model", "普通私聊")

    snapshot = queue_manager.snapshot()
    assert model_queue.private_queue.empty()
    assert snapshot["models"]["chat-model"]["group_superadmin"] == 0
    assert snapshot["models"]["chat-model"]["retry"] == 1
    assert snapshot["totals"]["retry"] == 1


def test_ai_request_max_retries_no_longer_clamped_to_five(tmp_path: Path) -> None:
    cfg = _load_config(
        tmp_path / "config.toml",
        """
[core]
bot_qq = 1
superadmin_qq = 2
ai_request_max_retries = 99

[onebot]
ws_url = "ws://127.0.0.1:3001"
token = ""

[models.chat]
api_url = "https://api.openai.com/v1"
api_key = "sk-chat"
model_name = "chat-model"
max_tokens = 1024

[models.vision]
api_url = "https://api.openai.com/v1"
api_key = "sk-vision"
model_name = "vision-model"

[models.security]
enabled = false
api_url = "https://api.openai.com/v1"
api_key = "sk-security"
model_name = "security-model"
max_tokens = 128

[models.agent]
api_url = "https://api.openai.com/v1"
api_key = "sk-agent"
model_name = "agent-model"
max_tokens = 1024
""",
    )

    assert cfg.ai_request_max_retries == 99
