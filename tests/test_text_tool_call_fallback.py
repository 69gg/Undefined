from __future__ import annotations

from collections.abc import Awaitable, Callable
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

from Undefined.ai.client import AIClient
from Undefined.config.models import ChatModelConfig


ToolExecutor = Callable[[str, dict[str, Any], dict[str, Any]], Awaitable[str]]


def _tool_schema(name: str) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": "test tool",
            "parameters": {"type": "object", "properties": {}},
        },
    }


def _build_client(
    *,
    responses: list[dict[str, Any]],
    tool_names: list[str],
    execute_tool: ToolExecutor,
) -> AIClient:
    client: Any = object.__new__(AIClient)
    client.runtime_config = SimpleNamespace(
        log_thinking=False,
        ai_request_max_retries=0,
        missing_tool_call_retries=0,
        tool_search_enabled=False,
        prefetch_tools=[],
        prefetch_tools_hide=False,
    )
    client._prompt_builder = SimpleNamespace(
        build_messages=AsyncMock(return_value=[{"role": "user", "content": "hello"}]),
        end_summaries=[],
    )
    client.tool_manager = SimpleNamespace(
        get_openai_tools=lambda: [_tool_schema(name) for name in tool_names],
        execute_tool=execute_tool,
    )
    client._filter_tools_for_runtime_config = lambda tools, **_kwargs: tools
    client._get_runtime_config = lambda: client.runtime_config
    client.model_selector = SimpleNamespace(wait_ready=AsyncMock())
    client.chat_config = ChatModelConfig(
        api_url="https://api.openai.com/v1",
        api_key="sk-test",
        model_name="chat-model",
        max_tokens=1024,
    )
    client._find_chat_config_by_name = lambda _name: client.chat_config
    client.submit_queued_llm_call = AsyncMock(side_effect=responses)
    client._search_wrapper = None
    client._end_summary_storage = None
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
    return cast(AIClient, client)


@pytest.mark.asyncio
async def test_text_tool_calls_use_normal_execution_and_stateless_replay() -> None:
    executed: list[tuple[str, dict[str, Any]]] = []

    async def execute_tool(
        name: str, arguments: dict[str, Any], context: dict[str, Any]
    ) -> str:
        executed.append((name, arguments))
        if name == "send_message":
            callback = cast(
                Callable[[str], Awaitable[None]], context["send_message_callback"]
            )
            await callback(str(arguments["message"]))
            return "消息发送成功"
        if name == "end":
            context["conversation_ended"] = True
            return "对话已结束"
        raise AssertionError(f"unexpected tool: {name}")

    first_content = """<tool name="send_message" params='{"message": "在做了在做了"}' />
<tool name="end" params='{"memo": "回应重试请求", "observations": ["一条观察"]}' />"""
    second_content = (
        '{"tool":"end","arguments":{"memo":"已回应","observations":["一条观察"]}}'
    )
    client = _build_client(
        responses=[
            {
                "_transport_state": {
                    "api_mode": "openai.responses",
                    "previous_response_id": "resp_1",
                    "tool_result_start_index": 2,
                },
                "choices": [{"message": {"content": first_content}}],
            },
            {"choices": [{"message": {"content": second_content}}]},
        ],
        tool_names=["send_message", "end"],
        execute_tool=execute_tool,
    )
    send_message = AsyncMock()

    result = await client.ask("hello", send_message_callback=send_message)

    assert result == ""
    assert [name for name, _arguments in executed] == ["send_message", "end"]
    send_message.assert_awaited_once_with("在做了在做了")
    submit = cast(AsyncMock, client.submit_queued_llm_call)
    assert submit.await_count == 2
    assert submit.await_args_list[1].kwargs["transport_state"] == {
        "api_mode": "openai.responses",
        "stateless_replay": True,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "content",
    [
        '{"tool":"hidden_tool","arguments":{}}',
        '{"tool":"end","arguments":{}} trailing',
    ],
)
async def test_invalid_or_unexposed_text_tool_protocol_is_never_sent(
    content: str,
) -> None:
    async def execute_tool(
        _name: str, _arguments: dict[str, Any], _context: dict[str, Any]
    ) -> str:
        raise AssertionError("rejected text tool protocol must not execute")

    client = _build_client(
        responses=[{"choices": [{"message": {"content": content}}]}],
        tool_names=["end"],
        execute_tool=execute_tool,
    )
    send_message = AsyncMock()

    result = await client.ask("hello", send_message_callback=send_message)

    assert result == ""
    send_message.assert_not_awaited()
    assert cast(AsyncMock, client.submit_queued_llm_call).await_count == 1
