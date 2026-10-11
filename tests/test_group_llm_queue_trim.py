"""Ordinary group traffic cannot abandon an already started ask's LLM call."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from Undefined.ai.client import AIClient
from Undefined.config.models import ChatModelConfig
from Undefined.services.coordinator import AICoordinator
from Undefined.services.queue_manager import QueueManager


async def _wait_until(predicate: Callable[[], bool]) -> None:
    async with asyncio.timeout(4):
        while not predicate():
            await asyncio.sleep(0.001)


def _coordinator(
    queue: QueueManager, *, fail_first: bool
) -> tuple[Any, Any, list[str]]:
    client: Any = object.__new__(AIClient)
    client._queue_manager = queue
    client._pending_llm_calls = {}
    client.runtime_config = SimpleNamespace(
        superadmin_qq=99999,
        ai_request_max_retries=int(fail_first),
        missing_tool_call_retries=0,
        tool_search_enabled=False,
        log_thinking=False,
    )
    client._get_runtime_config = lambda: client.runtime_config
    client.chat_config = ChatModelConfig(
        api_url="https://invalid.invalid/v1",
        api_key="isolated",
        model_name="audit",
        max_tokens=64,
    )
    client.tool_manager = SimpleNamespace(get_openai_tools=lambda: [])
    client._filter_tools_for_runtime_config = lambda tools, **kwargs: tools

    async def build_messages(question: str, **kwargs: Any) -> list[dict[str, Any]]:
        return [{"role": "user", "content": question}]

    client._prompt_builder = SimpleNamespace(
        build_messages=build_messages, end_summaries=[]
    )
    client._maybe_prefetch_tools = AsyncMock(
        side_effect=lambda messages, tools, call_type: (messages, None)
    )
    client.model_selector = SimpleNamespace(wait_ready=AsyncMock())
    client._search_wrapper = None
    client._end_summary_storage = None
    client._send_private_message_callback = None
    client._send_image_callback = None
    client.memory_storage = None
    client._knowledge_manager = None
    client._cognitive_service = None
    client._meme_service = None
    client._crawl4ai_capabilities = None
    attempts: list[str] = []

    async def model_request(**kwargs: Any) -> dict[str, Any]:
        original = "original-first" in str(kwargs["messages"])
        attempts.append("original" if original else "later")
        if fail_first and original and attempts.count("original") == 1:
            raise OSError("isolated retryable failure")
        return {
            "choices": [
                {
                    "message": {
                        "content": "original-result" if original else "later-result"
                    }
                }
            ]
        }

    client.request_model = model_request
    coordinator: Any = object.__new__(AICoordinator)
    coordinator.ai = client
    coordinator.config = SimpleNamespace(
        superadmin_qq=99999,
        bot_qq=88888,
        chat_model=client.chat_config,
        ai_request_max_retries=int(fail_first),
    )
    coordinator.queue_manager = queue
    coordinator.security = SimpleNamespace(
        detect_injection=AsyncMock(return_value=False)
    )
    coordinator.history_manager = SimpleNamespace(modify_last_group_message=AsyncMock())
    coordinator.onebot = SimpleNamespace(
        get_image=AsyncMock(), get_forward_msg=AsyncMock(), send_like=AsyncMock()
    )
    coordinator.sender = SimpleNamespace(
        send_group_message=AsyncMock(), send_private_message=AsyncMock()
    )
    coordinator.scheduler = None
    return coordinator, client, attempts


@pytest.mark.asyncio
@pytest.mark.parametrize("fail_first", [False, True])
async def test_started_normal_group_ask_survives_outer_queue_trim(
    fail_first: bool,
) -> None:
    queue = QueueManager(ai_request_interval=0.1, max_retries=int(fail_first))
    coordinator, client, attempts = _coordinator(queue, fail_first=fail_first)
    queue.start(coordinator.execute_reply)
    try:
        await coordinator.handle_auto_reply(
            group_id=12345, sender_id=20001, text="original-first", message_content=[]
        )
        if fail_first:
            await _wait_until(
                lambda: (
                    "audit" in queue._model_queues
                    and queue._model_queues["audit"].group_normal_queue.retry_count()
                    == 1
                )
            )
        else:
            await _wait_until(lambda: len(client._pending_llm_calls) == 1)
        original_request = next(iter(client._pending_llm_calls))
        for index in range(11):
            await coordinator.handle_auto_reply(
                group_id=12345,
                sender_id=30000 + index,
                text=f"later-{index}",
                message_content=[],
            )
        requests = list(queue._model_queues["audit"].group_normal_queue._items)
        assert requests[0]["request_id"] == original_request
        assert requests[0]["_queue_lane"] == "group_normal"
        assert requests[0].get("_retry_count", 0) == int(fail_first)
        assert [request.get("sender_id") for request in requests[1:]] == [
            30008,
            30009,
            30010,
        ]
        await _wait_until(
            lambda: (
                coordinator.sender.send_group_message.await_count == 4
                and not client._pending_llm_calls
                and queue._active_inflight_count() == 0
            )
        )
        assert attempts.count("original") == 1 + int(fail_first)
        assert queue._model_queues["audit"].group_normal_queue.empty()
        replies = [
            call.args[1]
            for call in coordinator.sender.send_group_message.await_args_list
        ]
        assert replies.count("original-result") == 1
        assert replies.count("later-result") == 3
    finally:
        await queue.stop()
