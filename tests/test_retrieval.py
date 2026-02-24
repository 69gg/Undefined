"""检索请求层测试。"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest
from openai import AsyncOpenAI

from Undefined.ai.retrieval import RetrievalRequester
from Undefined.ai.tokens import TokenCounter
from Undefined.config.models import EmbeddingModelConfig, RerankModelConfig


class _DummyCounter:
    def count(self, _text: str) -> int:
        return 0


def _make_requester(response_to_dict: Any | None = None) -> RetrievalRequester:
    return RetrievalRequester(
        get_openai_client=lambda _cfg: cast(AsyncOpenAI, object()),
        response_to_dict=response_to_dict or (lambda value: {"wrapped": value}),
        get_token_counter=lambda _model: cast(TokenCounter, _DummyCounter()),
        record_usage=lambda **_kwargs: None,
    )


def test_normalize_rerank_payload_accepts_list() -> None:
    requester = _make_requester()
    payload = requester._normalize_rerank_payload(
        [{"index": 0, "relevance_score": 0.9, "document": "doc"}]
    )
    assert payload == {
        "data": [{"index": 0, "relevance_score": 0.9, "document": "doc"}]
    }


def test_normalize_rerank_payload_accepts_dict() -> None:
    requester = _make_requester()
    payload = requester._normalize_rerank_payload({"results": [{"index": 0}]})
    assert payload == {"results": [{"index": 0}]}


def test_normalize_rerank_payload_handles_none() -> None:
    requester = _make_requester()
    assert requester._normalize_rerank_payload(None) == {}


def test_normalize_rerank_payload_uses_converter() -> None:
    requester = _make_requester(response_to_dict=lambda _value: {"results": []})
    payload = requester._normalize_rerank_payload(object())
    assert payload == {"results": []}


class _FakeEmbeddingsAPI:
    def __init__(self) -> None:
        self.last_kwargs: dict[str, Any] | None = None

    async def create(self, **kwargs: Any) -> Any:
        self.last_kwargs = dict(kwargs)
        return SimpleNamespace(
            data=[SimpleNamespace(embedding=[0.1, 0.2, 0.3])],
            usage={
                "prompt_tokens": 1,
                "completion_tokens": 0,
                "total_tokens": 1,
            },
        )


class _FakeClient:
    def __init__(self) -> None:
        self.embeddings = _FakeEmbeddingsAPI()


@pytest.mark.asyncio
async def test_embed_passes_dimensions_to_openai_sdk() -> None:
    fake_client = _FakeClient()
    requester = RetrievalRequester(
        get_openai_client=lambda _cfg: cast(AsyncOpenAI, fake_client),
        response_to_dict=lambda response: {
            "usage": getattr(response, "usage", {}),
        },
        get_token_counter=lambda _model: cast(TokenCounter, _DummyCounter()),
        record_usage=lambda **_kwargs: None,
    )
    cfg = EmbeddingModelConfig(
        api_url="https://api.openai.com/v1",
        api_key="sk-test",
        model_name="text-embedding-3-small",
        queue_interval_seconds=1.0,
        dimensions=768,
    )

    result = await requester.embed(cfg, ["hello"])

    assert result == [[0.1, 0.2, 0.3]]
    assert fake_client.embeddings.last_kwargs is not None
    assert fake_client.embeddings.last_kwargs["dimensions"] == 768


class _FakeRerankClient:
    def __init__(self) -> None:
        self.last_post_path: str | None = None
        self.last_post_body: dict[str, Any] | None = None

    async def post(self, path: str, *, cast_to: object, body: dict[str, Any]) -> Any:
        self.last_post_path = path
        self.last_post_body = dict(body)
        return {"results": [{"index": 1, "relevance_score": 0.88}]}


@pytest.mark.asyncio
async def test_rerank_disables_return_documents_in_request() -> None:
    fake_client = _FakeRerankClient()
    requester = RetrievalRequester(
        get_openai_client=lambda _cfg: cast(AsyncOpenAI, fake_client),
        response_to_dict=lambda response: cast(dict[str, Any], response),
        get_token_counter=lambda _model: cast(TokenCounter, _DummyCounter()),
        record_usage=lambda **_kwargs: None,
    )
    cfg = RerankModelConfig(
        api_url="https://api.openai.com/v1",
        api_key="sk-test",
        model_name="text-rerank-001",
        queue_interval_seconds=1.0,
    )
    documents = ["doc A", "doc B"]

    result = await requester.rerank(cfg, query="hello", documents=documents, top_n=1)

    assert fake_client.last_post_path == "/rerank"
    assert fake_client.last_post_body is not None
    assert fake_client.last_post_body["return_documents"] is False
    assert result == [{"index": 1, "relevance_score": 0.88, "document": "doc B"}]
