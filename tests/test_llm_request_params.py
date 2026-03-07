from __future__ import annotations

from typing import Any, cast

import httpx
import pytest
from openai import AsyncOpenAI

from Undefined.ai.llm import ModelRequester, _encode_tool_name_for_api
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
    def __init__(self, responses: list[dict[str, Any]] | None = None) -> None:
        self.last_kwargs: dict[str, Any] | None = None
        self.calls: list[dict[str, Any]] = []
        self._responses = list(responses or [])

    async def create(self, **kwargs: Any) -> dict[str, Any]:
        self.last_kwargs = dict(kwargs)
        self.calls.append(dict(kwargs))
        if not self._responses:
            raise AssertionError("fake responses exhausted")
        return self._responses.pop(0)


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

    await requester._http_client.aclose()


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
    messages = [
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
