from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

from Undefined.ai.client import AIClient
from Undefined.ai.tooling import END_CO_CALL_REJECT_CONTENT
from Undefined.config.models import ChatModelConfig


def _build_minimal_ai_client(
    *,
    execute_tool: Any,
    llm_responses: list[dict[str, Any]],
) -> Any:
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
    client.tool_manager = cast(
        Any,
        SimpleNamespace(
            get_openai_tools=lambda: [],
            execute_tool=execute_tool,
        ),
    )
    client._filter_tools_for_runtime_config = lambda tools, **_kwargs: tools
    client._get_runtime_config = cast(Any, lambda: client.runtime_config)
    client.model_selector = cast(Any, SimpleNamespace(wait_ready=AsyncMock()))
    client.chat_config = ChatModelConfig(
        api_url="https://api.openai.com/v1",
        api_key="sk-test",
        model_name="chat-model",
        max_tokens=1024,
    )
    client._find_chat_config_by_name = lambda _name: client.chat_config
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

    submit_calls: list[list[dict[str, Any]]] = []

    async def _submit_queued_llm_call(
        *,
        messages: list[dict[str, Any]],
        **kwargs: Any,
    ) -> dict[str, Any]:
        submit_calls.append(list(messages))
        index = len(submit_calls) - 1
        if index >= len(llm_responses):
            raise RuntimeError("unexpected extra llm call")
        return llm_responses[index]

    client.submit_queued_llm_call = AsyncMock(side_effect=_submit_queued_llm_call)
    client._submit_calls = submit_calls
    return client


@pytest.mark.asyncio
async def test_ai_ask_rejects_end_when_co_called_with_send_message() -> None:
    execute_calls: list[str] = []

    async def _execute_tool(
        name: str, args: dict[str, Any], ctx: dict[str, Any]
    ) -> str:
        execute_calls.append(name)
        if name == "send_message":
            ctx["message_sent_this_turn"] = True
            return "消息已发送（message_id=1）"
        if name == "end":
            ctx["conversation_ended"] = True
            return "对话已结束"
        return "ok"

    client = _build_minimal_ai_client(
        execute_tool=_execute_tool,
        llm_responses=[
            {
                "choices": [
                    {
                        "message": {
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "call_send",
                                    "function": {
                                        "name": "send_message",
                                        "arguments": '{"message":"喵"}',
                                    },
                                },
                                {
                                    "id": "call_end",
                                    "function": {
                                        "name": "end",
                                        "arguments": "{}",
                                    },
                                },
                            ],
                        }
                    }
                ],
            },
            {
                "choices": [
                    {
                        "message": {
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "call_end_only",
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
        ],
    )

    result = await AIClient.ask(client, "hello")

    assert result == ""
    assert execute_calls == ["send_message", "end"]
    assert len(client._submit_calls) == 2

    end_tool_messages = [
        m
        for m in client._submit_calls[1]
        if m.get("role") == "tool" and m.get("tool_call_id") == "call_end"
    ]
    assert len(end_tool_messages) == 1
    assert end_tool_messages[0]["content"] == END_CO_CALL_REJECT_CONTENT


@pytest.mark.asyncio
async def test_ai_ask_rejects_end_when_other_tool_failed() -> None:
    execute_calls: list[str] = []

    async def _execute_tool(
        name: str, args: dict[str, Any], ctx: dict[str, Any]
    ) -> str:
        execute_calls.append(name)
        if name == "send_message":
            raise RuntimeError("send failed")
        if name == "end":
            ctx["conversation_ended"] = True
            return "对话已结束"
        return "ok"

    client = _build_minimal_ai_client(
        execute_tool=_execute_tool,
        llm_responses=[
            {
                "choices": [
                    {
                        "message": {
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "call_send",
                                    "function": {
                                        "name": "send_message",
                                        "arguments": '{"message":"喵"}',
                                    },
                                },
                                {
                                    "id": "call_end",
                                    "function": {
                                        "name": "end",
                                        "arguments": "{}",
                                    },
                                },
                            ],
                        }
                    }
                ],
            },
            {
                "choices": [
                    {
                        "message": {
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "call_end_only",
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
        ],
    )

    result = await AIClient.ask(client, "hello")

    assert result == ""
    assert execute_calls == ["send_message", "end"]
    assert len(client._submit_calls) == 2

    end_tool_messages = [
        m
        for m in client._submit_calls[1]
        if m.get("role") == "tool" and m.get("tool_call_id") == "call_end"
    ]
    assert end_tool_messages[0]["content"] == END_CO_CALL_REJECT_CONTENT
