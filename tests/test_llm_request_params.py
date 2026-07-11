from __future__ import annotations

import hashlib
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import httpx
import pytest
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    BadRequestError,
)

from Undefined.ai.client import AIClient
from Undefined.ai.llm import (
    ModelRequester,
    _encode_tool_name_for_api,
    _should_fallback_from_stream,
    build_request_body,
)
from Undefined.ai.transports.openai_transport import (
    RESPONSES_OUTPUT_ITEMS_KEY,
    normalize_responses_result,
)
from Undefined.ai.parsing import extract_choices_content
from Undefined.config.models import ChatModelConfig
from Undefined.config.models import GrokModelConfig
from Undefined.context import RequestContext
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


class _FakeAsyncStream:
    def __init__(self, events: list[Any]) -> None:
        self._events = list(events)

    def __aiter__(self) -> _FakeAsyncStream:
        return self

    async def __anext__(self) -> Any:
        if not self._events:
            raise StopAsyncIteration
        return self._events.pop(0)


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


def _make_api_status_error(
    status_code: int,
    message: str,
    body: dict[str, Any],
) -> APIStatusError:
    request = httpx.Request("POST", "https://api.example.com/v1/chat/completions")
    response = httpx.Response(status_code, request=request, json=body)
    return APIStatusError(message, response=response, body=body)


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


class _FakeStreamingClient:
    def __init__(
        self,
        *,
        chat_events: list[dict[str, Any]] | None = None,
        response_events: list[dict[str, Any]] | None = None,
    ) -> None:
        self.chat = type(
            "_Chat",
            (),
            {
                "completions": SimpleNamespace(
                    last_kwargs=None,
                    calls=[],
                    create=self._create_chat(chat_events or []),
                )
            },
        )()
        self.responses = SimpleNamespace(
            last_kwargs=None,
            calls=[],
            create=self._create_responses(response_events or []),
        )

    def _create_chat(self, events: list[dict[str, Any]]) -> Any:
        async def _create(**kwargs: Any) -> _FakeAsyncStream:
            self.chat.completions.last_kwargs = dict(kwargs)
            self.chat.completions.calls.append(dict(kwargs))
            return _FakeAsyncStream(events)

        return _create

    def _create_responses(self, events: list[dict[str, Any]]) -> Any:
        async def _create(**kwargs: Any) -> _FakeAsyncStream:
            self.responses.last_kwargs = dict(kwargs)
            self.responses.calls.append(dict(kwargs))
            return _FakeAsyncStream(events)

        return _create


@pytest.mark.parametrize(
    ("api_mode", "token_field"),
    [
        ("openai.chat_completions", "max_tokens"),
        ("openai.responses", "max_output_tokens"),
        ("anthropic.messages", "max_tokens"),
    ],
)
@pytest.mark.parametrize("max_tokens", [0, -1])
def test_build_request_body_omits_non_positive_token_limit(
    api_mode: str,
    token_field: str,
    max_tokens: int,
) -> None:
    cfg = ChatModelConfig(
        api_url="https://api.example.com/v1",
        api_key="sk-test",
        model_name="test-model",
        max_tokens=max_tokens,
        api_mode=api_mode,
    )

    body = build_request_body(
        model_config=cfg,
        messages=[{"role": "user", "content": "hello"}],
        max_tokens=max_tokens,
    )

    assert token_field not in body


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
    assert fake_client.chat.completions.last_kwargs["metadata"] == {"source": "config"}
    assert fake_client.chat.completions.last_kwargs["reasoning_effort"] == "high"
    assert "extra_body" not in fake_client.chat.completions.last_kwargs
    assert (
        "ignored_keys=model,stream" in caplog.text
        or "ignored_keys=stream,model" in caplog.text
    )

    await requester._http_client.aclose()


@pytest.mark.asyncio
async def test_grok_request_defaults_to_chat_completions() -> None:
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
    cfg = GrokModelConfig(
        api_url="https://grok.example/v1",
        api_key="sk-grok",
        model_name="grok-4-search",
        max_tokens=1024,
        reasoning_enabled=True,
        reasoning_effort="low",
        request_params={"temperature": 0.3},
    )

    await requester.request(
        model_config=cfg,
        messages=[{"role": "user", "content": "latest AI chip news"}],
        max_tokens=256,
        call_type="grok_search",
    )

    assert fake_client.chat.completions.last_kwargs is not None
    assert fake_client.chat.completions.last_kwargs["model"] == "grok-4-search"
    assert fake_client.chat.completions.last_kwargs["max_tokens"] == 256
    assert fake_client.chat.completions.last_kwargs["temperature"] == 0.3
    assert fake_client.chat.completions.last_kwargs["reasoning_effort"] == "low"

    await requester._http_client.aclose()


@pytest.mark.asyncio
async def test_chat_request_strips_internal_reasoning_fields_from_messages() -> None:
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
        reasoning_content_replay=False,
    )
    tool_calls = [
        {
            "id": "call_1",
            "type": "function",
            "function": {
                "name": "lookup",
                "arguments": '{"query":"weather"}',
            },
        }
    ]

    await requester.request(
        model_config=cfg,
        messages=[
            {"role": "user", "content": "hello"},
            {
                "role": "assistant",
                "content": "",
                "phase": "commentary",
                "tool_calls": tool_calls,
                "reasoning_content": "内部思维链",
                RESPONSES_OUTPUT_ITEMS_KEY: [
                    {
                        "type": "reasoning",
                        "id": "rs_1",
                        "summary": [{"type": "summary_text", "text": "先想一下"}],
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call_1", "content": "done"},
        ],
        max_tokens=128,
        call_type="chat",
    )

    assert fake_client.chat.completions.last_kwargs is not None
    outbound_messages = fake_client.chat.completions.last_kwargs["messages"]
    assert outbound_messages[1] == {
        "role": "assistant",
        "content": "",
        "tool_calls": tool_calls,
    }
    assert "reasoning_content" not in outbound_messages[1]
    assert RESPONSES_OUTPUT_ITEMS_KEY not in outbound_messages[1]
    assert "phase" not in outbound_messages[1]

    await requester._http_client.aclose()


@pytest.mark.asyncio
async def test_chat_request_auto_sets_prompt_cache_key_from_request_context() -> None:
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
        prompt_cache_enabled=True,
    )

    async with RequestContext(request_type="group", group_id=12345, sender_id=10001):
        await requester.request(
            model_config=cfg,
            messages=[{"role": "user", "content": "hello"}],
            max_tokens=128,
            call_type="chat",
        )

    group_scope = hashlib.sha1(b"12345", usedforsecurity=False).hexdigest()[:8]
    assert fake_client.chat.completions.last_kwargs is not None
    assert (
        fake_client.chat.completions.last_kwargs["prompt_cache_key"]
        == f"pc:gpt-test:chat:group:{group_scope}"
    )

    await requester._http_client.aclose()


@pytest.mark.asyncio
async def test_chat_request_respects_prompt_cache_enabled_false() -> None:
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
        prompt_cache_enabled=False,
    )

    async with RequestContext(request_type="group", group_id=12345, sender_id=10001):
        await requester.request(
            model_config=cfg,
            messages=[{"role": "user", "content": "hello"}],
            max_tokens=128,
            call_type="chat",
        )

    assert fake_client.chat.completions.last_kwargs is not None
    assert "prompt_cache_key" not in fake_client.chat.completions.last_kwargs

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
    assert message[RESPONSES_OUTPUT_ITEMS_KEY] == [
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
    ]
    assert result["usage"] == {
        "prompt_tokens": 11,
        "completion_tokens": 7,
        "total_tokens": 18,
    }
    assert result["_transport_state"] == {
        "api_mode": "openai.responses",
        "previous_response_id": "resp_1",
        "tool_result_start_index": 2,
    }

    await requester._http_client.aclose()


@pytest.mark.asyncio
async def test_responses_request_maps_response_format_to_text_format() -> None:
    requester = ModelRequester(
        http_client=httpx.AsyncClient(),
        token_usage_storage=cast(TokenUsageStorage, _FakeUsageStorage()),
    )
    fake_client = _FakeClient(
        responses=[
            {
                "id": "resp_text",
                "output": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": '{"ok":true}'}],
                    }
                ],
                "usage": {"input_tokens": 5, "output_tokens": 3, "total_tokens": 8},
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
        request_params={
            "response_format": {"type": "json_object"},
            "verbosity": "low",
        },
    )

    await requester.request(
        model_config=cfg,
        messages=[{"role": "user", "content": "hello"}],
        max_tokens=128,
        call_type="chat",
    )

    assert fake_client.responses.last_kwargs is not None
    assert fake_client.responses.last_kwargs["text"] == {
        "format": {"type": "json_object"},
        "verbosity": "low",
    }
    assert "response_format" not in fake_client.responses.last_kwargs
    assert "extra_body" not in fake_client.responses.last_kwargs

    await requester._http_client.aclose()


@pytest.mark.asyncio
async def test_responses_request_respects_explicit_thinking_override() -> None:
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
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": "hi"}],
                    },
                ],
                "usage": {"input_tokens": 5, "output_tokens": 3, "total_tokens": 8},
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
    )

    await requester.request(
        model_config=cfg,
        messages=[{"role": "user", "content": "hello"}],
        max_tokens=128,
        call_type="chat",
        thinking={"enabled": False, "budget_tokens": 0},
    )

    assert fake_client.responses.last_kwargs is not None
    assert fake_client.responses.last_kwargs["reasoning"] == {"effort": "low"}
    assert fake_client.responses.last_kwargs["extra_body"] == {
        "thinking": {"budget_tokens": 0, "type": "disabled"},
    }

    await requester._http_client.aclose()


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


def test_responses_stateless_replay_uses_standard_output_items() -> None:
    normalized = normalize_responses_result(
        {
            "id": "resp_replay",
            "output": [
                {
                    "type": "reasoning",
                    "id": "rs_1",
                    "summary": [{"type": "summary_text", "text": "先想一下"}],
                    "encrypted_content": "enc_1",
                },
                {
                    "type": "function_call",
                    "call_id": "call_1",
                    "name": "lookup",
                    "arguments": '{"query":"weather"}',
                },
            ],
        }
    )
    assistant_message = normalized["choices"][0]["message"]

    cfg = ChatModelConfig(
        api_url="https://api.openai.com/v1",
        api_key="sk-test",
        model_name="gpt-test",
        max_tokens=512,
        api_mode="responses",
    )
    request_body = build_request_body(
        model_config=cfg,
        messages=[
            {"role": "user", "content": "hello"},
            assistant_message,
            {"role": "tool", "tool_call_id": "call_1", "content": "done"},
        ],
        max_tokens=128,
        transport_state={"stateless_replay": True},
    )

    assert request_body["include"] == ["reasoning.encrypted_content"]
    assert request_body["input"] == [
        {
            "type": "message",
            "role": "user",
            "content": [{"type": "input_text", "text": "hello"}],
        },
        {
            "type": "reasoning",
            "id": "rs_1",
            "summary": [{"type": "summary_text", "text": "先想一下"}],
            "encrypted_content": "enc_1",
        },
        {
            "type": "function_call",
            "call_id": "call_1",
            "name": "lookup",
            "arguments": '{"query":"weather"}',
        },
        {
            "type": "function_call_output",
            "call_id": "call_1",
            "output": "done",
        },
    ]


def test_responses_stateless_replay_moves_call_like_function_call_id_to_call_id() -> (
    None
):
    normalized = normalize_responses_result(
        {
            "id": "resp_replay_call_like_id",
            "output": [
                {
                    "type": "function_call",
                    "id": "call_1",
                    "name": "lookup",
                    "arguments": '{"query":"weather"}',
                },
            ],
        }
    )
    assistant_message = normalized["choices"][0]["message"]

    cfg = ChatModelConfig(
        api_url="https://api.openai.com/v1",
        api_key="sk-test",
        model_name="gpt-test",
        max_tokens=512,
        api_mode="responses",
    )
    request_body = build_request_body(
        model_config=cfg,
        messages=[
            {"role": "user", "content": "hello"},
            assistant_message,
            {"role": "tool", "tool_call_id": "call_1", "content": "done"},
        ],
        max_tokens=128,
        transport_state={"stateless_replay": True},
    )

    assert request_body["input"] == [
        {
            "type": "message",
            "role": "user",
            "content": [{"type": "input_text", "text": "hello"}],
        },
        {
            "type": "function_call",
            "call_id": "call_1",
            "name": "lookup",
            "arguments": '{"query":"weather"}',
        },
        {
            "type": "function_call_output",
            "call_id": "call_1",
            "output": "done",
        },
    ]


def test_build_request_body_responses_encodes_assistant_history_as_output_text() -> (
    None
):
    cfg = ChatModelConfig(
        api_url="https://api.openai.com/v1",
        api_key="sk-test",
        model_name="gpt-test",
        max_tokens=512,
        api_mode="responses",
    )

    body = build_request_body(
        model_config=cfg,
        messages=[
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi there"},
            {"role": "user", "content": "continue"},
        ],
        max_tokens=128,
    )

    assert body["input"] == [
        {
            "type": "message",
            "role": "user",
            "content": [{"type": "input_text", "text": "hello"}],
        },
        {
            "type": "message",
            "role": "assistant",
            "content": [{"type": "output_text", "text": "hi there"}],
        },
        {
            "type": "message",
            "role": "user",
            "content": [{"type": "input_text", "text": "continue"}],
        },
    ]


def test_build_request_body_responses_preserves_assistant_phase() -> None:
    cfg = ChatModelConfig(
        api_url="https://api.openai.com/v1",
        api_key="sk-test",
        model_name="gpt-test",
        max_tokens=512,
        api_mode="responses",
    )

    body = build_request_body(
        model_config=cfg,
        messages=[
            {
                "role": "assistant",
                "content": "working through it",
                "phase": "commentary",
            }
        ],
        max_tokens=128,
    )

    assert body["input"] == [
        {
            "type": "message",
            "role": "assistant",
            "phase": "commentary",
            "content": [{"type": "output_text", "text": "working through it"}],
        }
    ]


def test_normalize_responses_result_preserves_assistant_phase() -> None:
    normalized = normalize_responses_result(
        {
            "id": "resp_phase",
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "phase": "final_answer",
                    "content": [{"type": "output_text", "text": "done"}],
                }
            ],
        }
    )

    message = normalized["choices"][0]["message"]
    assert message["content"] == "done"
    assert message["phase"] == "final_answer"
    assert message[RESPONSES_OUTPUT_ITEMS_KEY] == [
        {
            "type": "message",
            "role": "assistant",
            "phase": "final_answer",
            "content": [{"type": "output_text", "text": "done"}],
        }
    ]


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


def test_build_request_body_responses_stateless_replay_strips_output_status() -> None:
    cfg = ChatModelConfig(
        api_url="https://api.openai.com/v1",
        api_key="sk-test",
        model_name="gpt-test",
        max_tokens=512,
        api_mode="responses",
    )
    body = build_request_body(
        model_config=cfg,
        messages=[
            {"role": "user", "content": "hello"},
            {
                "role": "assistant",
                "content": "",
                RESPONSES_OUTPUT_ITEMS_KEY: [
                    {
                        "type": "message",
                        "id": "msg_1",
                        "role": "assistant",
                        "status": "completed",
                        "content": [{"type": "output_text", "text": "all done"}],
                    }
                ],
            },
        ],
        max_tokens=128,
        transport_state={"api_mode": "responses", "stateless_replay": True},
    )

    replayed_message = body["input"][1]
    assert replayed_message["type"] == "message"
    assert "status" not in replayed_message


def test_responses_replay_cleans_only_nullable_function_call_fields() -> None:
    cfg = ChatModelConfig(
        api_url="https://api.openai.com/v1",
        api_key="sk-test",
        model_name="gpt-test",
        max_tokens=512,
        api_mode="openai.responses",
    )
    body = build_request_body(
        model_config=cfg,
        messages=[
            {
                "role": "assistant",
                "content": "",
                RESPONSES_OUTPUT_ITEMS_KEY: [
                    {
                        "type": "reasoning",
                        "id": "rs_1",
                        "summary": [],
                        "encrypted_content": None,
                    },
                    {
                        "type": "function_call",
                        "id": None,
                        "namespace": None,
                        "status": None,
                        "call_id": "call_1",
                        "name": "lookup",
                        "arguments": "{}",
                    },
                    {
                        "type": "function_call",
                        "id": "fc_2",
                        "namespace": "weather",
                        "status": "completed",
                        "call_id": "call_2",
                        "name": "lookup",
                        "arguments": "{}",
                    },
                ],
            }
        ],
        max_tokens=128,
        transport_state={"stateless_replay": True},
    )

    reasoning_item, plain_call, namespaced_call = body["input"]
    assert reasoning_item["encrypted_content"] is None
    assert "id" not in plain_call
    assert "namespace" not in plain_call
    assert "status" not in plain_call
    assert namespaced_call["id"] == "fc_2"
    assert namespaced_call["namespace"] == "weather"
    assert "status" not in namespaced_call


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
    setattr(client, "_filter_tools_for_runtime_config", lambda tools, **_kwargs: tools)
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
        "api_mode": "openai.responses",
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
        "api_mode": "openai.responses",
        "previous_response_id": "resp_2",
        "tool_result_start_index": 4,
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
        "api_mode": "openai.responses",
        "previous_response_id": "resp_2",
        "tool_result_start_index": 4,
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


@pytest.mark.parametrize(
    ("api_mode", "effort_field"),
    [
        ("openai.chat_completions", "reasoning_effort"),
        ("openai.responses", "reasoning"),
        ("anthropic.messages", "output_config"),
    ],
)
@pytest.mark.parametrize("effort", ["adaptive", "Vendor-Custom"])
def test_custom_reasoning_effort_follows_api_mode_unchanged(
    api_mode: str,
    effort_field: str,
    effort: str,
) -> None:
    cfg = ChatModelConfig(
        api_url="https://provider.example/v1",
        api_key="sk-test",
        model_name="reasoning-model",
        max_tokens=4096,
        api_mode=api_mode,
        reasoning_enabled=True,
        reasoning_effort=effort,
    )

    body = build_request_body(
        model_config=cfg,
        messages=[{"role": "user", "content": "hello"}],
        max_tokens=2048,
    )

    if effort_field == "reasoning_effort":
        assert body[effort_field] == effort
    else:
        assert body[effort_field]["effort"] == effort


@pytest.mark.asyncio
async def test_thinking_effort_follows_anthropic_messages_mode() -> None:
    """Anthropic mode maps thinking and effort without a style switch."""
    cfg = ChatModelConfig(
        api_url="https://api.anthropic.com/v1",
        api_key="sk-test",
        model_name="claude-test",
        max_tokens=16384,
        api_mode="anthropic.messages",
        thinking_enabled=True,
        thinking_budget_tokens=8000,
        reasoning_enabled=True,
        reasoning_effort="max",
    )

    body = build_request_body(
        model_config=cfg,
        messages=[{"role": "user", "content": "hello"}],
        max_tokens=10000,
    )

    assert body["thinking"] == {"type": "enabled", "budget_tokens": 8000}
    assert body["output_config"] == {"effort": "max"}
    assert "reasoning" not in body


@pytest.mark.asyncio
async def test_thinking_effort_follows_openai_responses_mode() -> None:
    """Responses mode maps custom effort into reasoning.effort."""
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
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": "hi"}],
                    },
                ],
                "usage": {"input_tokens": 5, "output_tokens": 3, "total_tokens": 8},
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
        max_tokens=4096,
        api_mode="openai.responses",
        thinking_enabled=True,
        thinking_budget_tokens=8000,
        reasoning_enabled=True,
        reasoning_effort="high",
    )

    await requester.request(
        model_config=cfg,
        messages=[{"role": "user", "content": "hello"}],
        max_tokens=1024,
        call_type="chat",
    )

    kw = fake_client.responses.last_kwargs
    assert kw is not None
    assert kw["extra_body"]["thinking"] == {"type": "enabled", "budget_tokens": 8000}
    assert kw["reasoning"] == {"effort": "high"}
    assert "output_config" not in kw and "output_config" not in kw.get("extra_body", {})

    await requester._http_client.aclose()


@pytest.mark.asyncio
async def test_thinking_enabled_legacy_budget_tokens() -> None:
    """thinking_enabled=True + no effort → legacy budget_tokens mode."""
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
        max_tokens=4096,
        thinking_enabled=True,
        thinking_budget_tokens=8000,
    )

    await requester.request(
        model_config=cfg,
        messages=[{"role": "user", "content": "hello"}],
        max_tokens=1024,
        call_type="chat",
    )

    kw = fake_client.chat.completions.last_kwargs
    assert kw is not None
    assert kw["extra_body"]["thinking"] == {"type": "enabled", "budget_tokens": 8000}

    await requester._http_client.aclose()


@pytest.mark.asyncio
async def test_chat_request_streaming_aggregates_content_and_tool_calls() -> None:
    requester = ModelRequester(
        http_client=httpx.AsyncClient(),
        token_usage_storage=cast(TokenUsageStorage, _FakeUsageStorage()),
    )
    fake_client = _FakeStreamingClient(
        chat_events=[
            {
                "choices": [
                    {
                        "delta": {"role": "assistant", "content": "hel"},
                        "finish_reason": None,
                    }
                ]
            },
            {
                "choices": [
                    {
                        "delta": {
                            "content": "lo",
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {"name": "lookup", "arguments": '{"q"'},
                                }
                            ],
                        },
                        "finish_reason": None,
                    }
                ]
            },
            {
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "function": {"arguments": ':"weather"}'},
                                }
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ],
                "usage": {
                    "prompt_tokens": 3,
                    "completion_tokens": 4,
                    "total_tokens": 7,
                },
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
        stream_enabled=True,
    )

    result = await requester.request(
        model_config=cfg,
        messages=[{"role": "user", "content": "hello"}],
        max_tokens=128,
        call_type="chat",
    )

    assert fake_client.chat.completions.last_kwargs is not None
    assert fake_client.chat.completions.last_kwargs["stream"] is True
    assert fake_client.chat.completions.last_kwargs["stream_options"] == {
        "include_usage": True
    }
    assert extract_choices_content(result) == "hello"
    assert result["choices"][0]["finish_reason"] == "tool_calls"
    assert result["choices"][0]["message"]["tool_calls"][0]["id"] == "call_1"
    assert (
        result["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"]
        == '{"q":"weather"}'
    )
    assert result["usage"] == {
        "prompt_tokens": 3,
        "completion_tokens": 4,
        "total_tokens": 7,
    }

    await requester._http_client.aclose()


@pytest.mark.asyncio
async def test_chat_request_streaming_preserves_content_whitespace() -> None:
    requester = ModelRequester(
        http_client=httpx.AsyncClient(),
        token_usage_storage=cast(TokenUsageStorage, _FakeUsageStorage()),
    )
    fake_client = _FakeStreamingClient(
        chat_events=[
            {"choices": [{"delta": {"role": "assistant", "content": "  code"}}]},
            {"choices": [{"delta": {"content": "\n  indented  "}}]},
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
        stream_enabled=True,
    )

    result = await requester.request(
        model_config=cfg,
        messages=[{"role": "user", "content": "hello"}],
        max_tokens=128,
        call_type="chat",
    )

    assert extract_choices_content(result) == "  code\n  indented  "

    await requester._http_client.aclose()


def test_stream_fallback_keeps_programming_errors_visible() -> None:
    request = httpx.Request("POST", "https://api.example.com/v1/chat/completions")

    assert _should_fallback_from_stream(
        _make_bad_request_error(
            "streaming unsupported",
            {"error": {"message": "streaming unsupported"}},
        )
    )
    assert _should_fallback_from_stream(NotImplementedError("streaming unavailable"))
    assert not _should_fallback_from_stream(
        _make_api_status_error(
            401,
            "invalid api key",
            {"error": {"message": "invalid api key"}},
        )
    )
    assert not _should_fallback_from_stream(
        _make_api_status_error(
            429,
            "rate limit",
            {"error": {"message": "rate limit exceeded"}},
        )
    )
    assert not _should_fallback_from_stream(APIConnectionError(request=request))
    assert not _should_fallback_from_stream(APITimeoutError(request=request))
    assert not _should_fallback_from_stream(AttributeError("parser bug"))
    assert not _should_fallback_from_stream(TypeError("unexpected event shape"))
    assert not _should_fallback_from_stream(ValueError("malformed internal state"))


@pytest.mark.asyncio
async def test_responses_request_streaming_prefers_completed_response_payload() -> None:
    requester = ModelRequester(
        http_client=httpx.AsyncClient(),
        token_usage_storage=cast(TokenUsageStorage, _FakeUsageStorage()),
    )
    fake_client = _FakeStreamingClient(
        response_events=[
            {"type": "response.output_text.delta", "delta": "partial "},
            {
                "type": "response.completed",
                "response": {
                    "id": "resp_stream",
                    "output": [
                        {
                            "type": "message",
                            "role": "assistant",
                            "content": [
                                {"type": "output_text", "text": "final answer"}
                            ],
                        }
                    ],
                    "usage": {
                        "input_tokens": 8,
                        "output_tokens": 5,
                        "total_tokens": 13,
                    },
                },
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
        stream_enabled=True,
    )

    result = await requester.request(
        model_config=cfg,
        messages=[{"role": "user", "content": "hello"}],
        max_tokens=128,
        call_type="chat",
    )

    assert fake_client.responses.last_kwargs is not None
    assert fake_client.responses.last_kwargs["stream"] is True
    assert extract_choices_content(result) == "final answer"
    assert result["usage"] == {
        "prompt_tokens": 8,
        "completion_tokens": 5,
        "total_tokens": 13,
    }

    await requester._http_client.aclose()


@pytest.mark.asyncio
async def test_responses_request_streaming_preserves_synthesized_whitespace() -> None:
    requester = ModelRequester(
        http_client=httpx.AsyncClient(),
        token_usage_storage=cast(TokenUsageStorage, _FakeUsageStorage()),
    )
    fake_client = _FakeStreamingClient(
        response_events=[
            {"type": "response.output_text.delta", "delta": "  code"},
            {"type": "response.output_text.delta", "delta": "\n  indented  "},
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
        stream_enabled=True,
    )

    result = await requester.request(
        model_config=cfg,
        messages=[{"role": "user", "content": "hello"}],
        max_tokens=128,
        call_type="chat",
    )

    assert extract_choices_content(result) == "  code\n  indented  "
    assert result["output_text"] == "  code\n  indented  "

    await requester._http_client.aclose()


@pytest.mark.asyncio
async def test_chat_request_preserves_reasoning_when_replay_enabled() -> None:
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
        reasoning_content_replay=True,
    )
    tool_calls = [
        {
            "id": "call_1",
            "type": "function",
            "function": {
                "name": "lookup",
                "arguments": '{"query":"weather"}',
            },
        }
    ]

    await requester.request(
        model_config=cfg,
        messages=[
            {"role": "user", "content": "hello"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": tool_calls,
                "reasoning_content": "内部思维链",
                RESPONSES_OUTPUT_ITEMS_KEY: [{"type": "reasoning", "id": "rs_1"}],
            },
            {"role": "tool", "tool_call_id": "call_1", "content": "done"},
        ],
        max_tokens=128,
        call_type="chat",
    )

    assert fake_client.chat.completions.last_kwargs is not None
    outbound_messages = fake_client.chat.completions.last_kwargs["messages"]
    assert outbound_messages[1]["reasoning_content"] == "内部思维链"
    assert RESPONSES_OUTPUT_ITEMS_KEY not in outbound_messages[1]

    await requester._http_client.aclose()


@pytest.mark.asyncio
async def test_chat_stream_replay_accumulates_reasoning_content() -> None:
    requester = ModelRequester(
        http_client=httpx.AsyncClient(),
        token_usage_storage=cast(TokenUsageStorage, _FakeUsageStorage()),
    )
    fake_client = _FakeStreamingClient(
        chat_events=[
            {
                "choices": [
                    {
                        "delta": {
                            "role": "assistant",
                            "reasoning_content": "think",
                        },
                        "finish_reason": None,
                    }
                ]
            },
            {
                "choices": [
                    {
                        "delta": {
                            "content": "ok",
                            "reasoning_content": "-more",
                        },
                        "finish_reason": "stop",
                    }
                ]
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
        stream_enabled=True,
        reasoning_content_replay=True,
    )

    result = await requester.request(
        model_config=cfg,
        messages=[{"role": "user", "content": "hello"}],
        max_tokens=128,
        call_type="chat",
    )

    assert result["choices"][0]["message"]["reasoning_content"] == "think-more"
    assert extract_choices_content(result) == "ok"

    await requester._http_client.aclose()


def test_responses_replay_requests_encrypted_reasoning_on_first_call() -> None:
    cfg = ChatModelConfig(
        api_url="https://api.openai.com/v1",
        api_key="sk-test",
        model_name="gpt-test",
        max_tokens=512,
        api_mode="responses",
        reasoning_content_replay=True,
    )
    request_body = build_request_body(
        model_config=cfg,
        messages=[{"role": "user", "content": "hello"}],
        max_tokens=128,
    )
    assert request_body["include"] == ["reasoning.encrypted_content"]
    assert "previous_response_id" not in request_body


def test_responses_replay_keeps_previous_response_id_incremental_path() -> None:
    normalized = normalize_responses_result(
        {
            "id": "resp_incr",
            "output": [
                {
                    "type": "function_call",
                    "call_id": "call_1",
                    "name": "lookup",
                    "arguments": '{"query":"weather"}',
                },
            ],
        }
    )
    assistant_message = normalized["choices"][0]["message"]
    cfg = ChatModelConfig(
        api_url="https://api.openai.com/v1",
        api_key="sk-test",
        model_name="gpt-test",
        max_tokens=512,
        api_mode="responses",
        reasoning_content_replay=True,
    )
    request_body = build_request_body(
        model_config=cfg,
        messages=[
            {"role": "user", "content": "hello"},
            assistant_message,
            {"role": "tool", "tool_call_id": "call_1", "content": "done"},
        ],
        max_tokens=128,
        transport_state={
            "previous_response_id": "resp_incr",
            "tool_result_start_index": 2,
        },
    )
    assert request_body["previous_response_id"] == "resp_incr"
    assert request_body["input"] == [
        {
            "type": "function_call_output",
            "call_id": "call_1",
            "output": "done",
        }
    ]
    assert "instructions" not in request_body


def test_system_prompt_as_user_merges_system_into_first_user() -> None:
    cfg = ChatModelConfig(
        api_url="https://api.openai.com/v1",
        api_key="sk-test",
        model_name="gpt-test",
        max_tokens=512,
        system_prompt_as_user=True,
    )
    request_body = build_request_body(
        model_config=cfg,
        messages=[
            {"role": "system", "content": "系统提示 A"},
            {"role": "developer", "content": "系统提示 B"},
            {"role": "user", "content": "用户问题"},
            {"role": "assistant", "content": "上一轮"},
        ],
        max_tokens=128,
    )
    outbound = request_body["messages"]
    assert all(msg.get("role") not in ("system", "developer") for msg in outbound)
    assert outbound[0]["role"] == "user"
    assert "系统提示 A" in outbound[0]["content"]
    assert "系统提示 B" in outbound[0]["content"]
    assert "用户问题" in outbound[0]["content"]
    assert outbound[1] == {"role": "assistant", "content": "上一轮"}
