from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import httpx
import pytest
from openai import AsyncOpenAI, BadRequestError

from Undefined.ai.client import AIClient
from Undefined.ai.llm import ModelRequester, _encode_tool_name_for_api
from Undefined.ai.transports.openai_transport import normalize_responses_result
from Undefined.ai.parsing import extract_choices_content
from Undefined.config.models import ChatModelConfig
from Undefined.token_usage_storage import TokenUsageStorage


class _FakeUsageStorage:
    async def record(self, _usage: Any) -> None:
        return None


class _FakeChatCompletionsAPI:
    def __init__(self, responses: list[dict[str, Any]] | None = None) -> None:
        self.last_kwargs: dict[str, Any] | None = None
        self.calls: list[dict[str, Any]] = []
        self._responses = list(responses or [])

    async def create(self, **kwargs: Any) -> dict[str, Any]:
        self.last_kwargs = dict(kwargs)
        self.calls.append(dict(kwargs))
        if self._responses:
            return self._responses.pop(0)
        return {
            "choices": [{"message": {"content": "ok"}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }


class _FakeResponsesAPI:
    def __init__(self, responses: list[Any] | None = None) -> None:
        self.last_kwargs: dict[str, Any] | None = None
        self.calls: list[dict[str, Any]] = []
        self._responses = list(responses or [])

    async def create(self, **kwargs: Any) -> dict[str, Any]:
        self.last_kwargs = dict(kwargs)
        self.calls.append(dict(kwargs))
        if not self._responses:
            raise AssertionError("fake responses exhausted")
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return cast(dict[str, Any], item)


def _make_bad_request_error(message: str, body: dict[str, Any]) -> BadRequestError:
    request = httpx.Request("POST", "https://api.example.com/v1/responses")
    response = httpx.Response(400, request=request)
    return BadRequestError(message, response=response, body=body)


class _FakeClient:
    def __init__(
        self,
        *,
        chat_responses: list[dict[str, Any]] | None = None,
        responses: list[dict[str, Any]] | None = None,
    ) -> None:
        self.chat = type(
            "_Chat", (), {"completions": _FakeChatCompletionsAPI(chat_responses)}
        )()
        self.responses = _FakeResponsesAPI(responses)


@pytest.mark.asyncio
async def test_chat_request_uses_model_reasoning_and_request_params(
    caplog: pytest.LogCaptureFixture,
) -> None:
    requester = ModelRequester(
        http_client=httpx.AsyncClient(),
        token_usage_storage=cast(TokenUsageStorage, _FakeUsageStorage()),
    )
    fake_client = _FakeClient()
    setattr(
        requester,
        "_get_openai_client_for_model",
        lambda _cfg: cast(AsyncOpenAI, fake_client),
    )
    cfg = ChatModelConfig(
        api_url="https://api.openai.com/v1",
        api_key="sk-test",
        model_name="gpt-test",
        max_tokens=512,
        reasoning_enabled=True,
        reasoning_effort="high",
        request_params={
            "temperature": 0.2,
            "metadata": {"source": "config"},
            "stream": True,
            "model": "should-be-ignored",
        },
    )

    await requester.request(
        model_config=cfg,
        messages=[{"role": "user", "content": "hello"}],
        max_tokens=128,
        call_type="chat",
        temperature=0.7,
    )

    assert fake_client.chat.completions.last_kwargs is not None
    assert fake_client.chat.completions.last_kwargs["model"] == "gpt-test"
    assert fake_client.chat.completions.last_kwargs["max_tokens"] == 128
    assert fake_client.chat.completions.last_kwargs["temperature"] == 0.7
    assert fake_client.chat.completions.last_kwargs["extra_body"] == {
        "metadata": {"source": "config"},
        "reasoning": {"effort": "high"},
    }
    assert (
        "ignored_keys=model,stream" in caplog.text
        or "ignored_keys=stream,model" in caplog.text
    )

    await requester._http_client.aclose()


@pytest.mark.asyncio
async def test_responses_request_normalizes_tool_calls_and_usage() -> None:
    requester = ModelRequester(
        http_client=httpx.AsyncClient(),
        token_usage_storage=cast(TokenUsageStorage, _FakeUsageStorage()),
    )
    fake_client = _FakeClient(
        responses=[
            {
                "id": "resp_1",
                "output": [
                    {
                        "type": "reasoning",
                        "id": "rs_1",
                        "summary": [{"type": "summary_text", "text": "先想一下"}],
                    },
                    {
                        "type": "function_call",
                        "call_id": "call_1",
                        "name": "lookup",
                        "arguments": '{"query": "weather"}',
                    },
                ],
                "usage": {"input_tokens": 11, "output_tokens": 7, "total_tokens": 18},
            }
        ]
    )
    setattr(
        requester,
        "_get_openai_client_for_model",
        lambda _cfg: cast(AsyncOpenAI, fake_client),
    )
    cfg = ChatModelConfig(
        api_url="https://api.openai.com/v1",
        api_key="sk-test",
        model_name="gpt-test",
        max_tokens=512,
        api_mode="responses",
        reasoning_enabled=True,
        reasoning_effort="low",
        request_params={
            "metadata": {"source": "config"},
            "custom_flag": "on",
        },
    )

    result = await requester.request(
        model_config=cfg,
        messages=[{"role": "user", "content": "hello"}],
        max_tokens=128,
        call_type="chat",
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "lookup",
                    "description": "lookup weather",
                    "parameters": {
                        "type": "object",
                        "properties": {"query": {"type": "string"}},
                        "required": ["query"],
                    },
                },
            }
        ],
        tool_choice=cast(Any, {"type": "function", "function": {"name": "lookup"}}),
        thinking={"enabled": False, "budget_tokens": 0},
    )

    assert fake_client.responses.last_kwargs is not None
    assert fake_client.responses.last_kwargs["model"] == "gpt-test"
    assert fake_client.responses.last_kwargs["max_output_tokens"] == 128
    assert fake_client.responses.last_kwargs["reasoning"] == {"effort": "low"}
    assert fake_client.responses.last_kwargs["tools"] == [
        {
            "type": "function",
            "name": "lookup",
            "description": "lookup weather",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        }
    ]
    assert fake_client.responses.last_kwargs["tool_choice"] == {
        "type": "function",
        "name": "lookup",
    }
    assert fake_client.responses.last_kwargs["metadata"] == {"source": "config"}
    assert fake_client.responses.last_kwargs["extra_body"] == {"custom_flag": "on"}
    assert "thinking" not in fake_client.responses.last_kwargs

    message = result["choices"][0]["message"]
    assert message["tool_calls"][0]["id"] == "call_1"
    assert message["tool_calls"][0]["function"]["name"] == "lookup"
    assert message["reasoning_content"] == "先想一下"
    assert result["usage"] == {
        "prompt_tokens": 11,
        "completion_tokens": 7,
        "total_tokens": 18,
    }
    assert result["_transport_state"] == {
        "api_mode": "responses",
        "previous_response_id": "resp_1",
        "tool_result_start_index": 2,
    }


def test_normalize_responses_result_falls_back_to_output_text_and_scalar_content() -> (
    None
):
    top_level = normalize_responses_result(
        {
            "id": "resp_top_level",
            "output": [],
            "output_text": "hello from gateway",
        }
    )
    assert top_level["choices"][0]["message"]["content"] == "hello from gateway"

    scalar_content = normalize_responses_result(
        {
            "id": "resp_scalar",
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": {"text": "hello from content object"},
                }
            ],
        }
    )
    assert scalar_content["choices"][0]["message"]["content"] == (
        "hello from content object"
    )


@pytest.mark.asyncio
async def test_responses_tool_choice_compat_mode_uses_required_string() -> None:
    requester = ModelRequester(
        http_client=httpx.AsyncClient(),
        token_usage_storage=cast(TokenUsageStorage, _FakeUsageStorage()),
    )
    fake_client = _FakeClient(
        responses=[
            {
                "id": "resp_compat",
                "output": [
                    {
                        "type": "function_call",
                        "call_id": "call_compat",
                        "name": "lookup",
                        "arguments": '{"query": "weather"}',
                    }
                ],
                "usage": {"input_tokens": 5, "output_tokens": 4, "total_tokens": 9},
            }
        ]
    )
    setattr(
        requester,
        "_get_openai_client_for_model",
        lambda _cfg: cast(AsyncOpenAI, fake_client),
    )
    cfg = ChatModelConfig(
        api_url="https://api.openai.com/v1",
        api_key="sk-test",
        model_name="gpt-test",
        max_tokens=512,
        api_mode="responses",
        responses_tool_choice_compat=True,
    )

    await requester.request(
        model_config=cfg,
        messages=[{"role": "user", "content": "hello"}],
        max_tokens=128,
        call_type="chat",
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "lookup",
                    "description": "lookup weather",
                    "parameters": {
                        "type": "object",
                        "properties": {"query": {"type": "string"}},
                        "required": ["query"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "search",
                    "description": "search docs",
                    "parameters": {
                        "type": "object",
                        "properties": {"query": {"type": "string"}},
                        "required": ["query"],
                    },
                },
            },
        ],
        tool_choice=cast(Any, {"type": "function", "function": {"name": "lookup"}}),
    )

    assert fake_client.responses.last_kwargs is not None
    assert fake_client.responses.last_kwargs["tool_choice"] == "required"
    assert fake_client.responses.last_kwargs["tools"] == [
        {
            "type": "function",
            "name": "lookup",
            "description": "lookup weather",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        }
    ]

    await requester._http_client.aclose()


@pytest.mark.asyncio
async def test_responses_transport_state_uses_previous_response_id_and_tool_outputs() -> (
    None
):
    requester = ModelRequester(
        http_client=httpx.AsyncClient(),
        token_usage_storage=cast(TokenUsageStorage, _FakeUsageStorage()),
    )
    fake_client = _FakeClient(
        responses=[
            {
                "id": "resp_1",
                "output": [
                    {
                        "type": "function_call",
                        "call_id": "call_1",
                        "name": "lookup",
                        "arguments": '{"query": "weather"}',
                    }
                ],
                "usage": {"input_tokens": 3, "output_tokens": 2, "total_tokens": 5},
            },
            {
                "id": "resp_2",
                "output": [
                    {
                        "type": "message",
                        "id": "msg_1",
                        "role": "assistant",
                        "status": "completed",
                        "content": [{"type": "output_text", "text": "all done"}],
                    }
                ],
                "usage": {"input_tokens": 4, "output_tokens": 3, "total_tokens": 7},
            },
        ]
    )
    setattr(
        requester,
        "_get_openai_client_for_model",
        lambda _cfg: cast(AsyncOpenAI, fake_client),
    )
    cfg = ChatModelConfig(
        api_url="https://api.openai.com/v1",
        api_key="sk-test",
        model_name="gpt-test",
        max_tokens=512,
        api_mode="responses",
        reasoning_enabled=True,
        reasoning_effort="medium",
    )
    tools = [
        {
            "type": "function",
            "function": {
                "name": "lookup",
                "description": "lookup weather",
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            },
        }
    ]

    first = await requester.request(
        model_config=cfg,
        messages=[{"role": "user", "content": "hello"}],
        max_tokens=128,
        call_type="chat",
        tools=tools,
    )
    first_tool_calls = first["choices"][0]["message"]["tool_calls"]
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "", "tool_calls": first_tool_calls},
        {"role": "tool", "tool_call_id": "call_1", "content": "done"},
    ]

    second = await requester.request(
        model_config=cfg,
        messages=messages,
        max_tokens=128,
        call_type="chat",
        tools=tools,
        transport_state=first["_transport_state"],
        message_count_for_transport=len(messages),
    )

    assert fake_client.responses.calls[1]["previous_response_id"] == "resp_1"
    assert fake_client.responses.calls[1]["input"] == [
        {
            "type": "function_call_output",
            "call_id": "call_1",
            "output": "done",
        }
    ]
    assert extract_choices_content(second) == "all done"
    assert second["usage"] == {
        "prompt_tokens": 4,
        "completion_tokens": 3,
        "total_tokens": 7,
    }


@pytest.mark.asyncio
async def test_ai_client_request_model_prefetch_keeps_transport_count_from_caller_messages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = object.__new__(AIClient)
    requester = AsyncMock(return_value={"choices": []})
    prefetch_mock = AsyncMock(
        return_value=(
            [
                {"role": "system", "content": "【预先工具结果】\n- lookup: done"},
                {"role": "user", "content": "hello"},
            ],
            [
                {
                    "type": "function",
                    "function": {
                        "name": "lookup",
                        "description": "lookup weather",
                        "parameters": {
                            "type": "object",
                            "properties": {"query": {"type": "string"}},
                            "required": ["query"],
                        },
                    },
                }
            ],
        )
    )
    setattr(client, "_requester", SimpleNamespace(request=requester))
    setattr(
        client,
        "tool_manager",
        SimpleNamespace(maybe_merge_agent_tools=lambda _call_type, tools: tools),
    )
    monkeypatch.setattr(client, "_maybe_prefetch_tools", prefetch_mock)

    cfg = ChatModelConfig(
        api_url="https://api.openai.com/v1",
        api_key="sk-test",
        model_name="gpt-test",
        max_tokens=512,
        api_mode="responses",
    )
    caller_messages: list[dict[str, Any]] = [{"role": "user", "content": "hello"}]
    tools = [
        {
            "type": "function",
            "function": {
                "name": "lookup",
                "description": "lookup weather",
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            },
        }
    ]

    await AIClient.request_model(
        client,
        model_config=cfg,
        messages=caller_messages,
        max_tokens=128,
        call_type="chat",
        tools=tools,
    )

    prefetch_mock.assert_awaited_once_with(caller_messages, tools, "chat")
    assert requester.await_count == 1
    assert requester.await_args is not None
    assert requester.await_args.kwargs["messages"] == [
        {"role": "system", "content": "【预先工具结果】\n- lookup: done"},
        {"role": "user", "content": "hello"},
    ]
    assert requester.await_args.kwargs["message_count_for_transport"] == len(
        caller_messages
    )


@pytest.mark.asyncio
async def test_responses_transport_state_uses_prefetched_message_count() -> None:
    requester = ModelRequester(
        http_client=httpx.AsyncClient(),
        token_usage_storage=cast(TokenUsageStorage, _FakeUsageStorage()),
    )
    fake_client = _FakeClient(
        responses=[
            {
                "id": "resp_prefetch",
                "output": [
                    {
                        "type": "function_call",
                        "call_id": "call_prefetch",
                        "name": "lookup",
                        "arguments": '{"query": "weather"}',
                    }
                ],
                "usage": {"input_tokens": 3, "output_tokens": 2, "total_tokens": 5},
            }
        ]
    )
    setattr(
        requester,
        "_get_openai_client_for_model",
        lambda _cfg: cast(AsyncOpenAI, fake_client),
    )
    cfg = ChatModelConfig(
        api_url="https://api.openai.com/v1",
        api_key="sk-test",
        model_name="gpt-test",
        max_tokens=512,
        api_mode="responses",
    )

    result = await requester.request(
        model_config=cfg,
        messages=[
            {"role": "system", "content": "prefetch result"},
            {"role": "user", "content": "hello"},
        ],
        max_tokens=128,
        call_type="chat",
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "lookup",
                    "description": "lookup weather",
                    "parameters": {
                        "type": "object",
                        "properties": {"query": {"type": "string"}},
                        "required": ["query"],
                    },
                },
            }
        ],
        message_count_for_transport=2,
    )

    assert result["_transport_state"] == {
        "api_mode": "responses",
        "previous_response_id": "resp_prefetch",
        "tool_result_start_index": 3,
    }

    await requester._http_client.aclose()
    requester = ModelRequester(
        http_client=httpx.AsyncClient(),
        token_usage_storage=cast(TokenUsageStorage, _FakeUsageStorage()),
    )
    fake_client = _FakeClient(
        responses=[
            {
                "id": "resp_2",
                "output": [
                    {
                        "type": "message",
                        "id": "msg_1",
                        "role": "assistant",
                        "status": "completed",
                        "content": [{"type": "output_text", "text": "all done"}],
                    }
                ],
                "usage": {"input_tokens": 6, "output_tokens": 3, "total_tokens": 9},
            }
        ]
    )
    setattr(
        requester,
        "_get_openai_client_for_model",
        lambda _cfg: cast(AsyncOpenAI, fake_client),
    )
    cfg = ChatModelConfig(
        api_url="https://api.openai.com/v1",
        api_key="sk-test",
        model_name="gpt-test",
        max_tokens=512,
        api_mode="responses",
        responses_force_stateless_replay=True,
    )
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": "hello"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {
                        "name": "lookup",
                        "arguments": '{"query": "weather"}',
                    },
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": "done"},
    ]

    result = await requester.request(
        model_config=cfg,
        messages=messages,
        max_tokens=128,
        call_type="chat",
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "lookup",
                    "description": "lookup weather",
                    "parameters": {
                        "type": "object",
                        "properties": {"query": {"type": "string"}},
                        "required": ["query"],
                    },
                },
            }
        ],
        transport_state={
            "api_mode": "responses",
            "previous_response_id": "resp_1",
            "tool_result_start_index": 2,
        },
        message_count_for_transport=len(messages),
    )

    assert "previous_response_id" not in fake_client.responses.calls[0]
    replay_input = fake_client.responses.calls[0]["input"]
    assert replay_input[0] == {
        "type": "message",
        "role": "user",
        "content": [{"type": "input_text", "text": "hello"}],
    }
    assert replay_input[1]["type"] == "function_call"
    assert replay_input[1]["call_id"] == "call_1"
    assert replay_input[2] == {
        "type": "function_call_output",
        "call_id": "call_1",
        "output": "done",
    }
    assert extract_choices_content(result) == "all done"
    assert result["_transport_state"] == {
        "api_mode": "responses",
        "previous_response_id": "resp_2",
        "tool_result_start_index": 3,
        "stateless_replay": True,
    }

    await requester._http_client.aclose()


@pytest.mark.asyncio
async def test_responses_followup_falls_back_to_stateless_replay_on_missing_call_id() -> (
    None
):
    requester = ModelRequester(
        http_client=httpx.AsyncClient(),
        token_usage_storage=cast(TokenUsageStorage, _FakeUsageStorage()),
    )
    fake_client = _FakeClient(
        responses=cast(
            list[dict[str, Any]],
            [
                _make_bad_request_error(
                    "No tool call found for function call output with call_id call_1.",
                    {
                        "error": {
                            "message": "No tool call found for function call output with call_id call_1.",
                            "type": "invalid_request_error",
                            "param": "input",
                            "code": None,
                        }
                    },
                ),
                {
                    "id": "resp_2",
                    "output": [
                        {
                            "type": "message",
                            "id": "msg_1",
                            "role": "assistant",
                            "status": "completed",
                            "content": [{"type": "output_text", "text": "all done"}],
                        }
                    ],
                    "usage": {"input_tokens": 6, "output_tokens": 3, "total_tokens": 9},
                },
            ],
        ),
    )
    setattr(
        requester,
        "_get_openai_client_for_model",
        lambda _cfg: cast(AsyncOpenAI, fake_client),
    )
    cfg = ChatModelConfig(
        api_url="https://api.openai.com/v1",
        api_key="sk-test",
        model_name="gpt-test",
        max_tokens=512,
        api_mode="responses",
    )
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": "hello"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {
                        "name": "lookup",
                        "arguments": '{"query": "weather"}',
                    },
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": "done"},
    ]

    result = await requester.request(
        model_config=cfg,
        messages=messages,
        max_tokens=128,
        call_type="chat",
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "lookup",
                    "description": "lookup weather",
                    "parameters": {
                        "type": "object",
                        "properties": {"query": {"type": "string"}},
                        "required": ["query"],
                    },
                },
            }
        ],
        transport_state={
            "api_mode": "responses",
            "previous_response_id": "resp_1",
            "tool_result_start_index": 2,
        },
        message_count_for_transport=len(messages),
    )

    assert fake_client.responses.calls[0]["previous_response_id"] == "resp_1"
    assert fake_client.responses.calls[0]["input"] == [
        {
            "type": "function_call_output",
            "call_id": "call_1",
            "output": "done",
        }
    ]
    assert "previous_response_id" not in fake_client.responses.calls[1]
    replay_input = fake_client.responses.calls[1]["input"]
    assert replay_input[0] == {
        "type": "message",
        "role": "user",
        "content": [{"type": "input_text", "text": "hello"}],
    }
    assert replay_input[1]["type"] == "function_call"
    assert replay_input[1]["call_id"] == "call_1"
    assert replay_input[1]["name"] == "lookup"
    assert replay_input[1]["arguments"] in {
        '{"query": "weather"}',
        '{"query":"weather"}',
    }
    assert replay_input[2] == {
        "type": "function_call_output",
        "call_id": "call_1",
        "output": "done",
    }
    assert extract_choices_content(result) == "all done"
    assert result["_transport_state"] == {
        "api_mode": "responses",
        "previous_response_id": "resp_2",
        "tool_result_start_index": 3,
        "stateless_replay": True,
    }

    await requester._http_client.aclose()


@pytest.mark.asyncio
async def test_responses_tools_and_tool_choice_use_sanitized_api_names() -> None:
    requester = ModelRequester(
        http_client=httpx.AsyncClient(),
        token_usage_storage=cast(TokenUsageStorage, _FakeUsageStorage()),
    )
    expected_api_name = _encode_tool_name_for_api("lookup.weather@bj")
    fake_client = _FakeClient(
        responses=[
            {
                "id": "resp_1",
                "output": [
                    {
                        "type": "function_call",
                        "call_id": "call_1",
                        "name": expected_api_name,
                        "arguments": '{"query": "weather"}',
                    }
                ],
                "usage": {"input_tokens": 2, "output_tokens": 3, "total_tokens": 5},
            }
        ]
    )
    setattr(
        requester,
        "_get_openai_client_for_model",
        lambda _cfg: cast(AsyncOpenAI, fake_client),
    )
    cfg = ChatModelConfig(
        api_url="https://api.openai.com/v1",
        api_key="sk-test",
        model_name="gpt-test",
        max_tokens=512,
        api_mode="responses",
        responses_tool_choice_compat=True,
    )

    result = await requester.request(
        model_config=cfg,
        messages=[{"role": "user", "content": "hello"}],
        max_tokens=128,
        call_type="chat",
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "lookup.weather@bj",
                    "description": "lookup weather",
                    "parameters": {
                        "type": "object",
                        "properties": {"query": {"type": "string"}},
                        "required": ["query"],
                    },
                },
            }
        ],
        tool_choice=cast(
            Any,
            {"type": "function", "function": {"name": "lookup.weather@bj"}},
        ),
    )

    assert fake_client.responses.last_kwargs is not None
    tool_payload = fake_client.responses.last_kwargs["tools"][0]
    api_tool_name = tool_payload["name"]
    assert tool_payload == {
        "type": "function",
        "name": api_tool_name,
        "description": "lookup weather",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    }
    assert api_tool_name != "lookup.weather@bj"
    assert fake_client.responses.last_kwargs["tool_choice"] == "required"
    assert result["choices"][0]["message"]["tool_calls"][0]["function"]["name"] == (
        "lookup.weather@bj"
    )

    await requester._http_client.aclose()
