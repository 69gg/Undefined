from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

from Undefined.ai.client import AIClient, MISSING_TOOL_CALL_RETRY_HINT
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
async def test_ai_ask_suppresses_queued_llm_error_when_retries_exhausted() -> None:
    client: Any = object.__new__(AIClient)
    client.runtime_config = cast(
        Any, SimpleNamespace(log_thinking=False, ai_request_max_retries=0)
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

    result = await AIClient.ask(client, "hello")

    assert result == ""


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

    async def _execute_tool(
        name: str, args: dict[str, Any], ctx: dict[str, Any]
    ) -> str:
        if name == "end":
            ctx["conversation_ended"] = True
            return "对话已结束"
        return "ok"

    client.tool_manager = cast(
        Any,
        SimpleNamespace(
            get_openai_tools=lambda: [],
            execute_tool=_execute_tool,
        ),
    )
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
            {
                "choices": [
                    {
                        "message": {
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "call_end",
                                    "function": {
                                        "name": "end",
                                        "arguments": "{}",
                                    },
                                }
                            ],
                        }
                    }
                ],
            },
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

    assert result == ""
    assert cast(AsyncMock, client.submit_queued_llm_call).await_count == 2


@pytest.mark.asyncio
async def test_ai_ask_webchat_events_include_stage_and_tool_lifecycle() -> None:
    client: Any = object.__new__(AIClient)
    client.runtime_config = cast(
        Any,
        SimpleNamespace(
            log_thinking=False,
            ai_request_max_retries=0,
            missing_tool_call_retries=0,
        ),
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

    seen_tool_context: dict[str, Any] = {}

    async def _execute_tool(
        name: str, args: dict[str, Any], ctx: dict[str, Any]
    ) -> str:
        _ = args
        seen_tool_context.update(ctx)
        if name == "end":
            ctx["conversation_ended"] = True
            return "对话已结束"
        return "tool result"

    client.tool_manager = cast(
        Any,
        SimpleNamespace(
            get_openai_tools=lambda: [],
            execute_tool=_execute_tool,
        ),
    )
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

    llm_results = [
        {
            "choices": [
                {
                    "message": {
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "function": {
                                    "name": "lookup",
                                    "arguments": '{"q":"weather"}',
                                },
                            }
                        ],
                    }
                }
            ]
        },
        {
            "choices": [
                {
                    "message": {
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "call_end",
                                "function": {"name": "end", "arguments": "{}"},
                            }
                        ],
                    }
                }
            ]
        },
    ]

    submit_index = 0

    async def _submit_queued_llm_call(**kwargs: Any) -> dict[str, Any]:
        nonlocal submit_index
        assert "stream_event_callback" not in kwargs
        result = llm_results[submit_index]
        submit_index += 1
        return result

    client.submit_queued_llm_call = AsyncMock(side_effect=_submit_queued_llm_call)
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
    events: list[tuple[str, dict[str, Any]]] = []

    async def _webchat_event_callback(event: str, payload: dict[str, Any]) -> None:
        events.append((event, dict(payload)))

    await AIClient.ask(
        client,
        "hello",
        extra_context={"webchat_event_callback": _webchat_event_callback},
    )

    event_names = [event for event, _payload in events]
    assert "stage" in event_names
    assert [event for event, _payload in events if event != "stage"] == [
        "tool_start",
        "tool_end",
        "tool_start",
        "tool_end",
    ]
    stage_names = [
        str(payload.get("stage") or "") for event, payload in events if event == "stage"
    ]
    assert "building_context" in stage_names
    assert "waiting_model" in stage_names
    assert "waiting_tools" in stage_names
    lifecycle_payloads = [payload for event, payload in events if event != "stage"]
    assert lifecycle_payloads[0]["name"] == "lookup"
    assert lifecycle_payloads[1]["result"] == "tool result"
    assert lifecycle_payloads[2]["name"] == "end"
    assert lifecycle_payloads[3]["result"] == "对话已结束"
    assert callable(seen_tool_context.get("render_html_to_image"))
    assert callable(seen_tool_context.get("render_markdown_to_html"))


@pytest.mark.asyncio
async def test_ai_ask_limits_missing_tool_call_retries() -> None:
    client: Any = object.__new__(AIClient)
    client.runtime_config = cast(
        Any,
        SimpleNamespace(
            log_thinking=False,
            ai_request_max_retries=0,
            missing_tool_call_retries=2,
        ),
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
    client.tool_manager = cast(
        Any,
        SimpleNamespace(
            get_openai_tools=lambda: [],
            execute_tool=AsyncMock(),
        ),
    )
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
    llm_responses = [
        {"choices": [{"message": {"content": "plain 1", "tool_calls": []}}]},
        {"choices": [{"message": {"content": "plain 2", "tool_calls": []}}]},
        {"choices": [{"message": {"content": "plain 3", "tool_calls": []}}]},
    ]
    submit_calls: list[list[dict[str, Any]]] = []

    async def _submit_queued_llm_call(
        *,
        messages: list[dict[str, Any]],
        **kwargs: Any,
    ) -> dict[str, Any]:
        submit_calls.append(list(messages))
        return llm_responses[len(submit_calls) - 1]

    client.submit_queued_llm_call = AsyncMock(side_effect=_submit_queued_llm_call)
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
    send_message = AsyncMock()

    result = await AIClient.ask(client, "hello", send_message_callback=send_message)

    assert result == ""
    assert cast(AsyncMock, client.submit_queued_llm_call).await_count == 3
    send_message.assert_awaited_once_with("plain 3")

    second_call_messages = submit_calls[1]
    assert second_call_messages[-2:] == [
        {"role": "assistant", "content": "plain 1"},
        {"role": "user", "content": MISSING_TOOL_CALL_RETRY_HINT},
    ]
    assert "send_message" not in MISSING_TOOL_CALL_RETRY_HINT


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
async def test_agent_runner_emits_nested_webchat_agent_stage(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
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
        submit_queued_llm_call=AsyncMock(
            return_value={"choices": [{"message": {"content": "done"}}]}
        ),
    )
    events: list[tuple[str, dict[str, Any]]] = []

    async def _webchat_event_callback(event: str, payload: dict[str, Any]) -> None:
        events.append((event, dict(payload)))

    monkeypatch.setattr(
        "Undefined.skills.agents.runner.context.AgentToolRegistry",
        lambda *_args, **_kwargs: SimpleNamespace(get_tools_schema=lambda: []),
    )

    result = await run_agent_with_tools(
        agent_name="demo_agent",
        user_content="用户需求：测试",
        empty_user_content_message="empty",
        default_prompt="你是一个测试助手。",
        context={
            "ai_client": cast(Any, ai_client),
            "runtime_config": SimpleNamespace(
                model_pool_enabled=False,
                ai_request_max_retries=0,
            ),
            "queue_lane": "private",
            "webchat_event_callback": _webchat_event_callback,
            "webchat_parent_call_id": "call_agent",
            "webchat_call_parent_id": "root_agent",
            "webchat_depth": 1,
            "webchat_agent_path": ["web_agent"],
        },
        agent_dir=agent_dir,
        logger=logging.getLogger("test_agent_runner_emits_webchat_agent_stage"),
        max_iterations=3,
    )

    assert result == "done"
    agent_stage_payloads = [
        payload for event, payload in events if event == "agent_stage"
    ]
    assert [str(payload.get("stage") or "") for payload in agent_stage_payloads] == [
        "context_ready",
        "waiting_model",
        "done",
    ]
    assert agent_stage_payloads[0]["webchat_call_id"] == "call_agent"
    assert agent_stage_payloads[0]["parent_webchat_call_id"] == "root_agent"
    assert agent_stage_payloads[0]["depth"] == 1
    assert agent_stage_payloads[0]["agent_path"] == ["web_agent"]
    assert "model=agent-model" in str(agent_stage_payloads[1]["detail"])


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
