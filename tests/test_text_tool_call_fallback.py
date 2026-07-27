from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

from Undefined.ai.client import AIClient
from Undefined.ai.llm.requester import build_request_body
from Undefined.ai.transports import (
    ANTHROPIC_CONTENT_BLOCKS_KEY,
    RESPONSES_OUTPUT_ITEMS_KEY,
)
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
    missing_tool_call_retries: int = 0,
) -> AIClient:
    client: Any = object.__new__(AIClient)
    client.runtime_config = SimpleNamespace(
        log_thinking=False,
        ai_request_max_retries=0,
        missing_tool_call_retries=missing_tool_call_retries,
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
    replayed_messages = submit.await_args_list[1].kwargs["messages"]
    recovered_message = next(
        message
        for message in replayed_messages
        if message.get("role") == "assistant"
        and [
            call.get("function", {}).get("name")
            for call in message.get("tool_calls", [])
        ]
        == ["send_message", "end"]
    )
    assert recovered_message["content"] == ""
    assert first_content not in [
        message.get("content") for message in replayed_messages
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "raw_content",
    [
        """<tool_execution>
<tool_call name="music-_-search_songs" arguments='{"query": "克罗地亚狂想曲 Maksim", "limit": 10}'>
</tool_call>
</tool_execution>""",
        """<function_calls>
<invoke name="music-_-search_songs">
<arguments>
{"query": "克罗地亚狂想曲 Maksim", "limit": 10}
</arguments>
</invoke>
</function_calls>""",
    ],
    ids=["tool_execution", "function_calls"],
)
async def test_xml_text_tool_envelope_uses_name_mapping_and_native_message_replay(
    raw_content: str,
) -> None:
    executed: list[tuple[str, dict[str, Any]]] = []

    async def execute_tool(
        name: str, arguments: dict[str, Any], context: dict[str, Any]
    ) -> str:
        executed.append((name, arguments))
        if name == "music.search_songs":
            return "搜索完成"
        if name == "end":
            context["conversation_ended"] = True
            return "对话已结束"
        raise AssertionError(f"unexpected tool: {name}")

    end_call = {
        "id": "call_end",
        "type": "function",
        "function": {"name": "end", "arguments": "{}"},
    }
    responses_reasoning_item = {
        "type": "reasoning",
        "id": "rs_1",
        "summary": [{"type": "summary_text", "text": "需要搜索音乐"}],
        "encrypted_content": "responses-ciphertext",
        "status": "completed",
    }
    anthropic_reasoning_blocks = [
        {
            "type": "thinking",
            "thinking": "需要搜索音乐",
            "signature": "thinking-signature",
        },
        {"type": "redacted_thinking", "data": "anthropic-ciphertext"},
    ]
    client = _build_client(
        responses=[
            {
                "_tool_name_map": {
                    "api_to_internal": {
                        "music-_-search_songs": "music.search_songs",
                        "end": "end",
                    }
                },
                "choices": [
                    {
                        "message": {
                            "content": raw_content,
                            "reasoning_content": "需要搜索音乐",
                            RESPONSES_OUTPUT_ITEMS_KEY: [
                                responses_reasoning_item,
                                {
                                    "type": "message",
                                    "role": "assistant",
                                    "content": [
                                        {"type": "output_text", "text": raw_content}
                                    ],
                                },
                            ],
                            ANTHROPIC_CONTENT_BLOCKS_KEY: [
                                *anthropic_reasoning_blocks,
                                {"type": "text", "text": raw_content},
                            ],
                        }
                    }
                ],
            },
            {"choices": [{"message": {"content": "", "tool_calls": [end_call]}}]},
        ],
        tool_names=["music.search_songs", "end"],
        execute_tool=execute_tool,
    )

    result = await client.ask("hello", send_message_callback=AsyncMock())

    assert result == ""
    assert executed == [
        (
            "music.search_songs",
            {"query": "克罗地亚狂想曲 Maksim", "limit": 10},
        ),
        ("end", {}),
    ]
    submit = cast(AsyncMock, client.submit_queued_llm_call)
    replayed_messages = submit.await_args_list[1].kwargs["messages"]
    recovered_message = next(
        message
        for message in replayed_messages
        if message.get("role") == "assistant"
        and message.get("tool_calls")
        and message["tool_calls"][0]["function"]["name"] == "music-_-search_songs"
    )
    assert recovered_message["content"] == ""
    assert recovered_message["reasoning_content"] == "需要搜索音乐"
    assert recovered_message[RESPONSES_OUTPUT_ITEMS_KEY] == [responses_reasoning_item]
    assert recovered_message[ANTHROPIC_CONTENT_BLOCKS_KEY] == (
        anthropic_reasoning_blocks
    )
    assert raw_content not in [message.get("content") for message in replayed_messages]

    recovered_call = recovered_message["tool_calls"][0]
    responses_body = build_request_body(
        ChatModelConfig(
            api_url="https://api.example.com/v1",
            api_key="sk-test",
            model_name="responses-model",
            api_mode="openai.responses",
            max_tokens=1024,
        ),
        [recovered_message],
        max_tokens=1024,
        transport_state={"stateless_replay": True},
    )
    assert [item["type"] for item in responses_body["input"]] == [
        "reasoning",
        "function_call",
    ]
    assert responses_body["input"][0]["encrypted_content"] == ("responses-ciphertext")
    assert responses_body["input"][1] == {
        "type": "function_call",
        "call_id": recovered_call["id"],
        "name": "music-_-search_songs",
        "arguments": recovered_call["function"]["arguments"],
    }

    anthropic_body = build_request_body(
        ChatModelConfig(
            api_url="https://api.example.com/v1",
            api_key="sk-test",
            model_name="anthropic-model",
            api_mode="anthropic.messages",
            max_tokens=4096,
        ),
        [recovered_message],
        max_tokens=4096,
    )
    assert anthropic_body["messages"][0]["content"] == [
        *anthropic_reasoning_blocks,
        {
            "type": "tool_use",
            "id": recovered_call["id"],
            "name": "music-_-search_songs",
            "input": {"query": "克罗地亚狂想曲 Maksim", "limit": 10},
        },
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("parallel_content", "expected_recovered_ids"),
    [
        (
            """{"name":"first_tool","arguments":{"value":1}}
{"name":"second_tool","arguments":{"value":2}}""",
            None,
        ),
        (
            '{"tool_calls":['
            '{"name":"first_tool","arguments":{"value":1}},'
            '{"name":"second_tool","arguments":{"value":2}}'
            "]}",
            None,
        ),
        (
            '{"tool_calls":['
            '{"id":"call_1","name":"first_tool","arguments":{"value":1}},'
            '{"id":"call_2","name":"second_tool","arguments":{"value":2}}'
            "]}",
            {"call_1", "call_2"},
        ),
    ],
    ids=[
        "consecutive_json",
        "tool_calls_json_envelope",
        "tool_calls_json_envelope_with_ids",
    ],
)
async def test_named_json_text_tools_execute_non_end_calls_in_parallel(
    parallel_content: str,
    expected_recovered_ids: set[str] | None,
) -> None:
    started: set[str] = set()
    all_started = asyncio.Event()

    async def execute_tool(
        name: str, arguments: dict[str, Any], context: dict[str, Any]
    ) -> str:
        if name in {"first_tool", "second_tool"}:
            started.add(name)
            if len(started) == 2:
                all_started.set()
            await asyncio.wait_for(all_started.wait(), timeout=1)
            return str(arguments["value"])
        if name == "end":
            context["conversation_ended"] = True
            return "对话已结束"
        raise AssertionError(f"unexpected tool: {name}")

    end_call = {
        "id": "call_end",
        "type": "function",
        "function": {"name": "end", "arguments": "{}"},
    }
    client = _build_client(
        responses=[
            {"choices": [{"message": {"content": parallel_content}}]},
            {"choices": [{"message": {"content": "", "tool_calls": [end_call]}}]},
        ],
        tool_names=["first_tool", "second_tool", "end"],
        execute_tool=execute_tool,
    )

    result = await client.ask("hello", send_message_callback=AsyncMock())

    assert result == ""
    assert started == {"first_tool", "second_tool"}
    submit = cast(AsyncMock, client.submit_queued_llm_call)
    replayed_messages = submit.await_args_list[1].kwargs["messages"]
    recovered_message = next(
        message
        for message in replayed_messages
        if message.get("role") == "assistant"
        and [
            call.get("function", {}).get("name")
            for call in message.get("tool_calls", [])
        ]
        == ["first_tool", "second_tool"]
    )
    recovered_ids = {str(call["id"]) for call in recovered_message["tool_calls"]}
    if expected_recovered_ids is not None:
        assert recovered_ids == expected_recovered_ids
    replayed_result_ids = {
        str(message.get("tool_call_id"))
        for message in replayed_messages
        if message.get("role") == "tool"
        and str(message.get("tool_call_id")) in recovered_ids
    }
    assert replayed_result_ids == recovered_ids
    assert parallel_content not in [
        message.get("content") for message in replayed_messages
    ]


@pytest.mark.asyncio
async def test_unexposed_text_tool_is_replayed_natively_and_rejected() -> None:
    executed: list[str] = []

    async def execute_tool(
        name: str, _arguments: dict[str, Any], context: dict[str, Any]
    ) -> str:
        executed.append(name)
        if name == "end":
            context["conversation_ended"] = True
            return "对话已结束"
        raise AssertionError("unexposed tool must not execute")

    hidden_content = '{"tool":"hidden_tool","arguments":{}}'
    end_call = {
        "id": "call_end",
        "type": "function",
        "function": {"name": "end", "arguments": "{}"},
    }
    client = _build_client(
        responses=[
            {"choices": [{"message": {"content": hidden_content}}]},
            {"choices": [{"message": {"content": "", "tool_calls": [end_call]}}]},
        ],
        tool_names=["end"],
        execute_tool=execute_tool,
    )

    result = await client.ask("hello", send_message_callback=AsyncMock())

    assert result == ""
    assert executed == ["end"]
    submit = cast(AsyncMock, client.submit_queued_llm_call)
    replayed_messages = submit.await_args_list[1].kwargs["messages"]
    hidden_call_message = next(
        message
        for message in replayed_messages
        if message.get("role") == "assistant"
        and message.get("tool_calls")
        and message["tool_calls"][0]["function"]["name"] == "hidden_tool"
    )
    hidden_call_id = hidden_call_message["tool_calls"][0]["id"]
    rejection = next(
        message
        for message in replayed_messages
        if message.get("role") == "tool"
        and message.get("tool_call_id") == hidden_call_id
    )
    assert "当前未加载或不可用" in rejection["content"]
    assert hidden_content not in [
        message.get("content") for message in replayed_messages
    ]


@pytest.mark.asyncio
async def test_invalid_text_tool_protocol_retries_then_sends_original_content() -> None:
    invalid_content = '{"tool":"end","arguments":{}} trailing'

    async def execute_tool(
        _name: str, _arguments: dict[str, Any], _context: dict[str, Any]
    ) -> str:
        raise AssertionError("invalid text tool protocol must not execute")

    client = _build_client(
        responses=[
            {"choices": [{"message": {"content": invalid_content}}]},
            {"choices": [{"message": {"content": invalid_content}}]},
        ],
        tool_names=["end"],
        execute_tool=execute_tool,
        missing_tool_call_retries=1,
    )
    send_message = AsyncMock()

    result = await client.ask("hello", send_message_callback=send_message)

    assert result == ""
    send_message.assert_awaited_once_with(invalid_content)
    submit = cast(AsyncMock, client.submit_queued_llm_call)
    assert submit.await_count == 2
    retried_messages = submit.await_args_list[1].kwargs["messages"]
    assert any(
        message.get("role") == "assistant" and message.get("content") == invalid_content
        for message in retried_messages
    )
    assert any(
        message.get("role") == "user"
        and "未调用任何工具" in str(message.get("content"))
        for message in retried_messages
    )
