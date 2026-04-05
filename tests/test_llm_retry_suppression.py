from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

from Undefined.ai.client import AIClient
from Undefined.ai.queue_budget import compute_queued_llm_timeout_seconds
from Undefined.config.models import (
    AgentModelConfig,
    ChatModelConfig,
    ModelPool,
    ModelPoolEntry,
)
from Undefined.context import RequestContext
from Undefined.skills.agents.runner import run_agent_with_tools


@pytest.mark.asyncio
async def test_ai_ask_reraises_queued_llm_error() -> None:
    client: Any = object.__new__(AIClient)
    client._prompt_builder = cast(
        Any,
        SimpleNamespace(
            build_messages=AsyncMock(
                return_value=[{"role": "user", "content": "hello"}]
            ),
            end_summaries=[],
        ),
    )
    client.tool_manager = cast(Any, SimpleNamespace(get_openai_tools=lambda: []))
    client._filter_tools_for_runtime_config = lambda tools: tools
    client._get_runtime_config = cast(
        Any, lambda: cast(Any, SimpleNamespace(log_thinking=False))
    )
    client.model_selector = cast(Any, SimpleNamespace(wait_ready=AsyncMock()))
    client.chat_config = ChatModelConfig(
        api_url="https://api.openai.com/v1",
        api_key="sk-test",
        model_name="chat-model",
        max_tokens=1024,
    )
    client._find_chat_config_by_name = lambda _name: client.chat_config
    client.submit_queued_llm_call = AsyncMock(side_effect=RuntimeError("boom"))
    client._search_wrapper = None
    client._end_summary_storage = cast(Any, None)
    client._send_private_message_callback = None
    client._send_image_callback = None
    client.memory_storage = None
    client._knowledge_manager = None
    client._cognitive_service = None
    client._meme_service = None
    client._crawl4ai_capabilities = SimpleNamespace(
        available=False,
        error=None,
        proxy_config_available=False,
    )

    with pytest.raises(RuntimeError, match="boom"):
        await AIClient.ask(client, "hello")


@pytest.mark.asyncio
async def test_ai_ask_retries_pre_tool_local_failure() -> None:
    client: Any = object.__new__(AIClient)
    client.runtime_config = cast(
        Any, SimpleNamespace(log_thinking=False, ai_request_max_retries=1)
    )
    client._prompt_builder = cast(
        Any,
        SimpleNamespace(
            build_messages=AsyncMock(
                return_value=[{"role": "user", "content": "hello"}]
            ),
            end_summaries=[],
        ),
    )
    client.tool_manager = cast(Any, SimpleNamespace(get_openai_tools=lambda: []))
    client._filter_tools_for_runtime_config = lambda tools: tools
    client._get_runtime_config = cast(Any, lambda: client.runtime_config)
    client.model_selector = cast(Any, SimpleNamespace(wait_ready=AsyncMock()))
    client.chat_config = ChatModelConfig(
        api_url="https://api.openai.com/v1",
        api_key="sk-test",
        model_name="chat-model",
        max_tokens=1024,
    )
    client._find_chat_config_by_name = lambda _name: client.chat_config
    client.submit_queued_llm_call = AsyncMock(
        side_effect=[
            {"choices": []},
            {"choices": [{"message": {"content": "ok"}}]},
        ]
    )
    client._search_wrapper = None
    client._end_summary_storage = cast(Any, None)
    client._send_private_message_callback = None
    client._send_image_callback = None
    client.memory_storage = None
    client._knowledge_manager = None
    client._cognitive_service = None
    client._meme_service = None
    client._crawl4ai_capabilities = SimpleNamespace(
        available=False,
        error=None,
        proxy_config_available=False,
    )

    result = await AIClient.ask(client, "hello")

    assert result == "ok"
    assert cast(AsyncMock, client.submit_queued_llm_call).await_count == 2


@pytest.mark.asyncio
async def test_agent_runner_reraises_queued_llm_error(tmp_path: Path) -> None:
    agent_dir = tmp_path / "demo_agent"
    (agent_dir / "tools").mkdir(parents=True)

    agent_config = AgentModelConfig(
        api_url="https://api.openai.com/v1",
        api_key="sk-test",
        model_name="agent-model",
        max_tokens=512,
    )
    ai_client = SimpleNamespace(
        agent_config=agent_config,
        model_selector=SimpleNamespace(
            select_agent_config=lambda config, **_kwargs: config
        ),
        submit_queued_llm_call=AsyncMock(side_effect=RuntimeError("boom")),
    )

    with pytest.raises(RuntimeError, match="智能体模型请求失败"):
        await run_agent_with_tools(
            agent_name="demo_agent",
            user_content="用户需求：测试",
            empty_user_content_message="empty",
            default_prompt="你是一个测试助手。",
            context={
                "ai_client": cast(Any, ai_client),
                "runtime_config": SimpleNamespace(
                    model_pool_enabled=False,
                    ai_request_max_retries=1,
                ),
                "queue_lane": "private",
            },
            agent_dir=agent_dir,
            logger=logging.getLogger("test_agent_runner_reraises_queued_llm_error"),
            max_iterations=3,
        )


@pytest.mark.asyncio
async def test_submit_queued_llm_call_enqueues_requested_lane() -> None:
    client: Any = object.__new__(AIClient)
    client._queue_manager = cast(Any, SimpleNamespace())
    client._pending_llm_calls = {}
    client.request_model = cast(Any, AsyncMock())
    client.runtime_config = cast(Any, SimpleNamespace(ai_request_max_retries=2))

    async def _enqueue(
        request: dict[str, object], *, lane: str, model_name: str
    ) -> None:
        assert lane == "group_superadmin"
        assert model_name == "chat-model"
        assert request["type"] == "queued_llm_call"
        assert request["group_id"] == 123
        assert request["user_id"] == 456
        client.set_llm_call_result(str(request["request_id"]), {"choices": []})

    client._queue_manager.add_queued_llm_request = cast(Any, _enqueue)

    model_config = ChatModelConfig(
        api_url="https://api.openai.com/v1",
        api_key="sk-test",
        model_name="chat-model",
        max_tokens=1024,
    )

    async with RequestContext(request_type="group", group_id=123, user_id=456) as ctx:
        ctx.set_resource("queue_lane", "group_superadmin")
        result = await AIClient.submit_queued_llm_call(
            client,
            model_config=model_config,
            messages=[{"role": "user", "content": "hello"}],
        )

    assert result == {"choices": []}


@pytest.mark.asyncio
async def test_resolve_queue_lane_infers_foreground_from_request_context() -> None:
    client: Any = object.__new__(AIClient)
    client.runtime_config = cast(
        Any, SimpleNamespace(superadmin_qq=10001, ai_request_max_retries=2)
    )
    client._get_runtime_config = cast(Any, lambda: client.runtime_config)

    async with RequestContext(
        request_type="private",
        user_id=42,
        sender_id=10001,
    ):
        assert AIClient._resolve_queue_lane(client) == "superadmin"

    async with RequestContext(
        request_type="group",
        group_id=123,
        user_id=20002,
        sender_id=20002,
    ) as ctx:
        ctx.set_resource("is_at_bot", True)
        assert AIClient._resolve_queue_lane(client) == "group_mention"


def test_queued_llm_wait_timeout_scales_with_retry_count() -> None:
    client: Any = object.__new__(AIClient)
    client.runtime_config = cast(Any, SimpleNamespace(ai_request_max_retries=1))
    client.chat_config = ChatModelConfig(
        api_url="https://api.openai.com/v1",
        api_key="sk-test",
        model_name="chat-model",
        max_tokens=1024,
        queue_interval_seconds=600.0,
    )
    client._get_runtime_config = cast(Any, lambda: client.runtime_config)

    assert AIClient._get_queued_llm_wait_timeout_seconds(client) == 2190.0


def test_compute_queued_llm_timeout_seconds_uses_max_pool_interval() -> None:
    runtime_config = SimpleNamespace(ai_request_max_retries=2)
    model_config = ChatModelConfig(
        api_url="https://api.openai.com/v1",
        api_key="sk-test",
        model_name="chat-model",
        max_tokens=1024,
        queue_interval_seconds=5.0,
        pool=ModelPool(
            enabled=True,
            models=[
                ModelPoolEntry(
                    api_url="https://api.openai.com/v1",
                    api_key="sk-a",
                    model_name="pool-a",
                    max_tokens=1024,
                    queue_interval_seconds=10.0,
                ),
                ModelPoolEntry(
                    api_url="https://api.openai.com/v1",
                    api_key="sk-b",
                    model_name="pool-b",
                    max_tokens=1024,
                    queue_interval_seconds=30.0,
                ),
            ],
        ),
    )

    assert compute_queued_llm_timeout_seconds(runtime_config, model_config) == 1560.0


def test_compute_queued_llm_timeout_seconds_avoids_double_counting_initial_wait() -> (
    None
):
    runtime_config = SimpleNamespace(ai_request_max_retries=0)
    model_config = ChatModelConfig(
        api_url="https://api.openai.com/v1",
        api_key="sk-test",
        model_name="chat-model",
        max_tokens=1024,
        queue_interval_seconds=600.0,
    )

    assert (
        compute_queued_llm_timeout_seconds(
            runtime_config,
            model_config,
            initial_wait_seconds=599.0,
            include_first_dispatch_interval=False,
        )
        == 1109.0
    )
