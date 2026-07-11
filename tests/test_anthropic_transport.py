from __future__ import annotations

import json
from types import TracebackType
from typing import Any, cast

import httpx
import pytest
from anthropic import AsyncAnthropic, omit

from Undefined.ai.llm import ModelRequester, build_request_body
from Undefined.ai.transports import (
    ANTHROPIC_CONTENT_BLOCKS_KEY,
    normalize_anthropic_result,
)
from Undefined.config.models import ChatModelConfig
from Undefined.token_usage_storage import TokenUsageStorage


class _FakeUsageStorage:
    async def record(self, _usage: Any) -> None:
        return None


class _FakeMessageStream:
    def __init__(self, final_message: dict[str, Any]) -> None:
        self._final_message = final_message
        self._iterated = False

    async def __aenter__(self) -> _FakeMessageStream:
        return self

    async def __aexit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        return None

    def __aiter__(self) -> _FakeMessageStream:
        return self

    async def __anext__(self) -> dict[str, Any]:
        if self._iterated:
            raise StopAsyncIteration
        self._iterated = True
        return {"type": "message_start"}

    async def get_final_message(self) -> dict[str, Any]:
        return self._final_message


class _FakeMessagesAPI:
    def __init__(self, response: dict[str, Any]) -> None:
        self._response = response
        self.create_calls: list[dict[str, Any]] = []
        self.stream_calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> dict[str, Any]:
        self.create_calls.append(dict(kwargs))
        return self._response

    def stream(self, **kwargs: Any) -> _FakeMessageStream:
        self.stream_calls.append(dict(kwargs))
        return _FakeMessageStream(self._response)


class _FakeAnthropicClient:
    def __init__(self, response: dict[str, Any]) -> None:
        self.messages = _FakeMessagesAPI(response)


def _config(**overrides: Any) -> ChatModelConfig:
    values: dict[str, Any] = {
        "api_url": "https://api.anthropic.com/v1",
        "api_key": "sk-ant-test",
        "model_name": "claude-test",
        "max_tokens": 8192,
        "api_mode": "anthropic.messages",
    }
    values.update(overrides)
    return ChatModelConfig(**values)


@pytest.mark.parametrize("effort", ["adaptive", "xhigh", "Vendor-Custom"])
def test_anthropic_effort_is_passed_through_unchanged(effort: str) -> None:
    body = build_request_body(
        model_config=_config(reasoning_enabled=True, reasoning_effort=effort),
        messages=[{"role": "user", "content": "hello"}],
        max_tokens=4096,
    )

    assert body["output_config"]["effort"] == effort


def test_anthropic_manual_thinking_system_images_tools_and_output_config() -> None:
    tools: list[dict[str, Any]] = [
        {
            "type": "function",
            "function": {
                "name": "lookup",
                "description": "Look up data",
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
                "strict": True,
            },
        }
    ]
    body = build_request_body(
        model_config=_config(
            thinking_enabled=True,
            thinking_budget_tokens=2048,
            reasoning_enabled=True,
            reasoning_effort="high",
        ),
        messages=[
            {"role": "system", "content": "system instruction"},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "inspect"},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": "data:image/png;base64,AAAA",
                            "detail": "auto",
                        },
                    },
                ],
            },
        ],
        max_tokens=4096,
        tools=tools,
        tool_choice="auto",
        output_config={"format": {"type": "json_schema", "schema": {}}},
    )

    assert body["system"] == "system instruction"
    assert body["messages"][0]["content"] == [
        {"type": "text", "text": "inspect"},
        {
            "type": "image",
            "source": {"type": "base64", "media_type": "image/png", "data": "AAAA"},
        },
    ]
    assert body["thinking"] == {"type": "enabled", "budget_tokens": 2048}
    assert body["output_config"] == {
        "format": {"type": "json_schema", "schema": {}},
        "effort": "high",
    }
    assert body["tools"][0]["input_schema"] == tools[0]["function"]["parameters"]
    assert body["tools"][0]["strict"] is True


def test_anthropic_adaptive_thinking_and_manual_budget_validation() -> None:
    adaptive_body = build_request_body(
        model_config=_config(
            thinking_enabled=True,
            thinking_include_budget=False,
            thinking_budget_tokens=0,
        ),
        messages=[{"role": "user", "content": "hello"}],
        max_tokens=4096,
    )
    assert adaptive_body["thinking"] == {"type": "adaptive"}

    with pytest.raises(ValueError, match="thinking_budget_tokens >= 1024"):
        build_request_body(
            model_config=_config(
                thinking_enabled=True,
                thinking_include_budget=True,
                thinking_budget_tokens=1023,
            ),
            messages=[{"role": "user", "content": "hello"}],
            max_tokens=4096,
        )

    with pytest.raises(ValueError, match="小于本次 max_tokens"):
        build_request_body(
            model_config=_config(
                thinking_enabled=True,
                thinking_include_budget=True,
                thinking_budget_tokens=4096,
            ),
            messages=[{"role": "user", "content": "hello"}],
            max_tokens=4096,
        )

    for unlimited_max_tokens in (0, -1):
        unlimited_body = build_request_body(
            model_config=_config(
                thinking_enabled=True,
                thinking_include_budget=True,
                thinking_budget_tokens=4096,
            ),
            messages=[{"role": "user", "content": "hello"}],
            max_tokens=unlimited_max_tokens,
        )
        assert "max_tokens" not in unlimited_body
        assert unlimited_body["thinking"] == {
            "type": "enabled",
            "budget_tokens": 4096,
        }

    override_body = build_request_body(
        model_config=_config(),
        messages=[{"role": "user", "content": "hello"}],
        max_tokens=0,
        thinking={"type": "enabled", "budget_tokens": 4096},
    )
    assert "max_tokens" not in override_body
    assert override_body["thinking"] == {
        "type": "enabled",
        "budget_tokens": 4096,
    }


def test_anthropic_disabled_thinking_keeps_forced_tool_choice() -> None:
    tool = {
        "type": "function",
        "function": {
            "name": "lookup",
            "parameters": {"type": "object", "properties": {}},
        },
    }
    body = build_request_body(
        model_config=_config(thinking_enabled=True),
        messages=[{"role": "user", "content": "hello"}],
        max_tokens=4096,
        tools=[tool],
        tool_choice={"type": "function", "function": {"name": "lookup"}},
        thinking={"type": "disabled"},
    )

    assert body["thinking"] == {"type": "disabled"}
    assert body["tool_choice"] == {"type": "tool", "name": "lookup"}


def test_anthropic_raw_thinking_blocks_replay_in_original_order() -> None:
    content_blocks = [
        {"type": "thinking", "thinking": "analysis", "signature": "sig"},
        {"type": "redacted_thinking", "data": "cipher"},
        {"type": "text", "text": "calling tool"},
        {"type": "tool_use", "id": "toolu_1", "name": "lookup", "input": {}},
    ]
    normalized = normalize_anthropic_result(
        {
            "id": "msg_1",
            "content": content_blocks,
            "stop_reason": "tool_use",
            "usage": {
                "input_tokens": 10,
                "cache_creation_input_tokens": 2,
                "cache_read_input_tokens": 3,
                "output_tokens": 4,
            },
        }
    )
    message = normalized["choices"][0]["message"]
    assert message[ANTHROPIC_CONTENT_BLOCKS_KEY] == content_blocks
    assert message["reasoning_content"] == "analysis"
    assert normalized["usage"] == {
        "prompt_tokens": 15,
        "completion_tokens": 4,
        "total_tokens": 19,
    }

    replay_body = build_request_body(
        model_config=_config(),
        messages=[
            message,
            {"role": "tool", "tool_call_id": "toolu_1", "content": "done"},
        ],
        max_tokens=4096,
    )
    assert replay_body["messages"][0]["content"] == content_blocks

    disabled_body = build_request_body(
        model_config=_config(reasoning_content_replay=False),
        messages=[
            message,
            {"role": "tool", "tool_call_id": "toolu_1", "content": "done"},
        ],
        max_tokens=4096,
    )
    assert disabled_body["messages"][0]["content"] == content_blocks[2:]


@pytest.mark.asyncio
@pytest.mark.parametrize("stream_enabled", [False, True])
@pytest.mark.parametrize("max_tokens", [4096, 0, -1])
async def test_requester_uses_anthropic_sdk_messages_interface(
    stream_enabled: bool,
    max_tokens: int,
) -> None:
    response = {
        "id": "msg_1",
        "content": [{"type": "text", "text": "hello"}],
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 2, "output_tokens": 1},
    }
    fake_client = _FakeAnthropicClient(response)
    http_client = httpx.AsyncClient()
    requester = ModelRequester(
        http_client=http_client,
        token_usage_storage=cast(TokenUsageStorage, _FakeUsageStorage()),
    )
    setattr(
        requester,
        "_get_anthropic_client_for_model",
        lambda _cfg: cast(AsyncAnthropic, fake_client),
    )

    result = await requester.request(
        model_config=_config(
            max_tokens=max_tokens,
            stream_enabled=stream_enabled,
            reasoning_enabled=True,
            reasoning_effort="high",
            request_params={
                "cache_control": {"type": "ephemeral"},
                "output_config": {
                    "effort": "low",
                    "format": {"type": "json_schema", "schema": {}},
                },
            },
        ),
        messages=[{"role": "user", "content": "hello"}],
        max_tokens=max_tokens,
        call_type="chat",
    )

    assert result["choices"][0]["message"]["content"] == "hello"
    if stream_enabled:
        assert len(fake_client.messages.stream_calls) == 1
        assert fake_client.messages.create_calls == []
        request_kwargs = fake_client.messages.stream_calls[0]
    else:
        assert len(fake_client.messages.create_calls) == 1
        assert fake_client.messages.stream_calls == []
        request_kwargs = fake_client.messages.create_calls[0]
    assert request_kwargs["output_config"] == {
        "effort": "high",
        "format": {"type": "json_schema", "schema": {}},
    }
    assert request_kwargs["cache_control"] == {"type": "ephemeral"}
    if max_tokens > 0:
        assert request_kwargs["max_tokens"] == max_tokens
    else:
        assert request_kwargs["max_tokens"] is omit
    await http_client.aclose()


@pytest.mark.asyncio
async def test_anthropic_sdk_omits_non_positive_max_tokens_from_http_body() -> None:
    request_body: dict[str, Any] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        decoded = json.loads(request.content)
        assert isinstance(decoded, dict)
        request_body.update(decoded)
        return httpx.Response(
            200,
            request=request,
            json={
                "id": "msg_1",
                "type": "message",
                "role": "assistant",
                "model": "claude-test",
                "content": [{"type": "text", "text": "hello"}],
                "stop_reason": "end_turn",
                "stop_sequence": None,
                "usage": {"input_tokens": 2, "output_tokens": 1},
            },
        )

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    anthropic_client = AsyncAnthropic(
        api_key="sk-ant-test",
        base_url="https://provider.example",
        timeout=480.0,
        http_client=http_client,
    )
    requester = ModelRequester(
        http_client=http_client,
        token_usage_storage=cast(TokenUsageStorage, _FakeUsageStorage()),
    )
    setattr(
        requester,
        "_get_anthropic_client_for_model",
        lambda _cfg: anthropic_client,
    )

    result = await requester.request(
        model_config=_config(max_tokens=0),
        messages=[{"role": "user", "content": "hello"}],
        max_tokens=0,
    )

    assert result["choices"][0]["message"]["content"] == "hello"
    assert "max_tokens" not in request_body
    await anthropic_client.close()
