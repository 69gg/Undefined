"""检索请求层测试。"""

from __future__ import annotations

from typing import Any, cast

from openai import AsyncOpenAI
from Undefined.ai.retrieval import RetrievalRequester
from Undefined.ai.tokens import TokenCounter


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
