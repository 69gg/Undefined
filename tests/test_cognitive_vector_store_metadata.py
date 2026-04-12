from __future__ import annotations

import asyncio
from collections import OrderedDict
from types import SimpleNamespace
from typing import Any, cast

import pytest
from chromadb.errors import InternalError as ChromaInternalError

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


@pytest.mark.asyncio
async def test_query_retries_transient_chroma_internal_error() -> None:
    class _FakeCollection:
        name = "cognitive_events"

        def __init__(self) -> None:
            self.calls = 0

        def query(self, **_kwargs: object) -> dict[str, list[list[object]]]:
            self.calls += 1
            if self.calls < 3:
                raise ChromaInternalError(
                    "Error executing plan: Internal error: Error finding id"
                )
            return {
                "documents": [["事件A"]],
                "metadatas": [[{"timestamp_local": "2026-04-11 19:43:01"}]],
                "distances": [[0.1]],
            }

    store = CognitiveVectorStore.__new__(CognitiveVectorStore)
    store._events_lock = asyncio.Lock()
    store._profiles_lock = asyncio.Lock()
    fake_collection = _FakeCollection()
    store._events = cast(Any, fake_collection)
    store._profiles = cast(Any, object())

    results = await store._query(
        fake_collection,
        "测试查询",
        1,
        None,
        None,
        1,
        query_embedding=[0.11, 0.22, 0.33],
    )

    assert fake_collection.calls == 3
    assert results == [
        {
            "document": "事件A",
            "metadata": {"timestamp_local": "2026-04-11 19:43:01"},
            "distance": 0.1,
        }
    ]
