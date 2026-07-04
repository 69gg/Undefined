from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, cast

import httpx
import pytest

import Undefined.ai.llm.requester as requester_module
from Undefined.ai.llm import ModelRequester
from Undefined.config.models import ChatModelConfig
from Undefined.token_usage_storage import TokenUsageStorage


class _FakeUsageStorage:
    async def record(self, _usage: Any) -> None:
        return None


class _FakeAsyncClient:
    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


class _FakeOpenAI:
    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs


def _chat_config(*, use_proxy: bool) -> ChatModelConfig:
    return ChatModelConfig(
        api_url="https://api.example.com/v1",
        api_key="sk-test",
        model_name="gpt-test",
        max_tokens=512,
        use_proxy=use_proxy,
    )


def test_model_requester_uses_proxy_only_when_model_enables_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created_http_clients: list[_FakeAsyncClient] = []

    class FakeAsyncClientFactory(_FakeAsyncClient):
        def __init__(self, **kwargs: Any) -> None:
            super().__init__(**kwargs)
            created_http_clients.append(self)

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClientFactory)
    monkeypatch.setattr(requester_module, "AsyncOpenAI", _FakeOpenAI)

    requester = ModelRequester(
        None,
        cast(TokenUsageStorage, _FakeUsageStorage()),
        config_getter=lambda: SimpleNamespace(
            http_proxy="http://proxy.local:7890",
            https_proxy="http://proxy.local:7891",
        ),
    )

    proxied = requester._get_openai_client_for_model(_chat_config(use_proxy=True))
    direct = requester._get_openai_client_for_model(_chat_config(use_proxy=False))

    assert isinstance(proxied, _FakeOpenAI)
    assert isinstance(direct, _FakeOpenAI)
    assert created_http_clients[0].kwargs["proxy"] == "http://proxy.local:7891"
    assert created_http_clients[0].kwargs["trust_env"] is False
    assert "proxy" not in created_http_clients[1].kwargs
    assert created_http_clients[1].kwargs["trust_env"] is False


@pytest.mark.asyncio
async def test_clear_client_cache_defers_active_owned_client_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created_http_clients: list[_FakeAsyncClient] = []

    class FakeAsyncClientFactory(_FakeAsyncClient):
        def __init__(self, **kwargs: Any) -> None:
            super().__init__(**kwargs)
            created_http_clients.append(self)

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClientFactory)
    monkeypatch.setattr(requester_module, "AsyncOpenAI", _FakeOpenAI)

    requester = ModelRequester(
        None,
        cast(TokenUsageStorage, _FakeUsageStorage()),
    )

    first_client = requester._get_openai_client_for_model(_chat_config(use_proxy=False))
    first_http_client = created_http_clients[0]

    async with requester._track_openai_client_use(first_client):
        requester.clear_client_cache()
        second_client = requester._get_openai_client_for_model(
            _chat_config(use_proxy=False)
        )

        assert isinstance(second_client, _FakeOpenAI)
        assert created_http_clients[1] is not first_http_client
        assert first_http_client.closed is False

    await asyncio.sleep(0)

    assert first_http_client.closed is True
    assert created_http_clients[1].closed is False
