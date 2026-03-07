from __future__ import annotations

from typing import Any, cast

import httpx
import pytest
from openai import AsyncOpenAI

from Undefined.ai.llm import ModelRequester
from Undefined.config.models import ChatModelConfig
from Undefined.token_usage_storage import TokenUsageStorage


class _FakeUsageStorage:
    async def record(self, _usage: Any) -> None:
        return None


class _FakeChatCompletionsAPI:
    def __init__(self) -> None:
        self.last_kwargs: dict[str, Any] | None = None

    async def create(self, **kwargs: Any) -> dict[str, Any]:
        self.last_kwargs = dict(kwargs)
        return {
            "choices": [{"message": {"content": "ok"}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }


class _FakeChatClient:
    def __init__(self) -> None:
        self.chat = type("_Chat", (), {"completions": _FakeChatCompletionsAPI()})()


@pytest.mark.asyncio
async def test_request_uses_model_request_params_and_call_overrides(
    caplog: pytest.LogCaptureFixture,
) -> None:
    requester = ModelRequester(
        http_client=httpx.AsyncClient(),
        token_usage_storage=cast(TokenUsageStorage, _FakeUsageStorage()),
    )
    fake_client = _FakeChatClient()
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
        reasoning_effort="high",
    )

    assert fake_client.chat.completions.last_kwargs is not None
    assert fake_client.chat.completions.last_kwargs["model"] == "gpt-test"
    assert fake_client.chat.completions.last_kwargs["max_tokens"] == 128
    assert fake_client.chat.completions.last_kwargs["temperature"] == 0.7
    assert fake_client.chat.completions.last_kwargs["extra_body"] == {
        "metadata": {"source": "config"},
        "reasoning_effort": "high",
    }
    assert (
        "ignored_keys=model,stream" in caplog.text
        or "ignored_keys=stream,model" in caplog.text
    )

    await requester._http_client.aclose()
