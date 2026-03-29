from __future__ import annotations

import asyncio
from collections import OrderedDict
from types import SimpleNamespace

import pytest

from Undefined.cognitive.vector_store import _sanitize_metadata
from Undefined.cognitive.vector_store import CognitiveVectorStore


def test_sanitize_metadata_drops_empty_message_ids_list() -> None:
    metadata = {
        "request_id": "req-1",
        "message_ids": [],
        "end_seq": 1,
    }

    result = _sanitize_metadata(metadata)

    assert result["request_id"] == "req-1"
    assert result["end_seq"] == 1
    assert "message_ids" not in result


def test_sanitize_metadata_keeps_non_empty_message_ids_list() -> None:
    metadata = {
        "message_ids": ["10001", " ", 10002, None],
        "user_id": "42",
    }

    result = _sanitize_metadata(metadata)

    assert result["user_id"] == "42"
    assert result["message_ids"] == ["10001", 10002]


@pytest.mark.asyncio
async def test_embed_query_cache_reuses_recent_embedding() -> None:
    class _FakeEmbedder:
        query_instruction = "query: "

        def __init__(self) -> None:
            self.calls = 0
            self._embedding_model = SimpleNamespace(
                model_name="text-embedding-test",
                dimensions=3,
            )

        async def embed(self, texts: list[str]) -> list[list[float]]:
            self.calls += 1
            _ = texts
            return [[0.11, 0.22, 0.33]]

    store = CognitiveVectorStore.__new__(CognitiveVectorStore)
    store._embedder = _FakeEmbedder()
    store._query_embedding_cache = OrderedDict()
    store._query_embedding_cache_lock = asyncio.Lock()

    first = await store.embed_query("  hello world  ")
    second = await store.embed_query("hello world")

    assert first == [0.11, 0.22, 0.33]
    assert second == [0.11, 0.22, 0.33]
    assert store._embedder.calls == 1
