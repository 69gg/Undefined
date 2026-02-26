from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from Undefined.config.models import EmbeddingModelConfig, RerankModelConfig
from Undefined.knowledge.manager import KnowledgeManager
from Undefined.knowledge.runtime import RetrievalRuntime


class _DummyRequester:
    async def embed(
        self,
        _model_config: EmbeddingModelConfig,
        texts: list[str],
    ) -> list[list[float]]:
        return [[0.0] * 3 for _ in texts]

    async def rerank(
        self,
        model_config: RerankModelConfig,
        query: str,
        documents: list[str],
        top_n: int | None = None,
    ) -> list[dict[str, Any]]:
        limit = len(documents) if top_n is None else min(len(documents), top_n)
        return [
            {"index": i, "relevance_score": 1.0, "document": documents[i]}
            for i in range(limit)
        ]


def _make_kb(tmp_path: Path, name: str, files: dict[str, str]) -> None:
    kb_dir = tmp_path / name
    texts_dir = kb_dir / "texts"
    texts_dir.mkdir(parents=True)
    for fname, content in files.items():
        file_path = texts_dir / fname
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, "utf-8")


@pytest.mark.asyncio
async def test_runtime_reuses_singleton_embedder_and_reranker() -> None:
    runtime = RetrievalRuntime(
        _DummyRequester(),  # type: ignore[arg-type]
        EmbeddingModelConfig(
            api_url="https://api.openai.com/v1",
            api_key="sk-embed",
            model_name="text-embedding-3-small",
            queue_interval_seconds=0.2,
            dimensions=1024,
        ),
        RerankModelConfig(
            api_url="https://api.openai.com/v1",
            api_key="sk-rerank",
            model_name="text-rerank-001",
            queue_interval_seconds=0.3,
        ),
        embed_batch_size=16,
    )

    embedder1 = runtime.ensure_embedder()
    embedder2 = runtime.ensure_embedder()
    reranker1 = runtime.ensure_reranker()
    reranker2 = runtime.ensure_reranker()

    try:
        assert embedder1 is embedder2
        assert reranker1 is not None
        assert reranker1 is reranker2
        assert abs(embedder1.interval - 0.2) < 1e-9
        assert abs(reranker1.interval - 0.3) < 1e-9
    finally:
        await runtime.stop()


@pytest.mark.asyncio
async def test_runtime_returns_none_when_rerank_model_not_ready() -> None:
    runtime = RetrievalRuntime(
        _DummyRequester(),  # type: ignore[arg-type]
        EmbeddingModelConfig(
            api_url="https://api.openai.com/v1",
            api_key="sk-embed",
            model_name="text-embedding-3-small",
            queue_interval_seconds=0.2,
            dimensions=None,
        ),
        RerankModelConfig(
            api_url="",
            api_key="",
            model_name="",
            queue_interval_seconds=0.3,
        ),
    )

    try:
        assert runtime.rerank_model_ready is False
        assert runtime.ensure_reranker() is None
    finally:
        await runtime.stop()


@pytest.mark.asyncio
async def test_knowledge_manager_can_use_retrieval_runtime(tmp_path: Path) -> None:
    runtime = RetrievalRuntime(
        _DummyRequester(),  # type: ignore[arg-type]
        EmbeddingModelConfig(
            api_url="https://api.openai.com/v1",
            api_key="sk-embed",
            model_name="text-embedding-3-small",
            queue_interval_seconds=0.0,
            query_instruction="Q: ",
            document_instruction="D: ",
        ),
        RerankModelConfig(
            api_url="https://api.openai.com/v1",
            api_key="sk-rerank",
            model_name="text-rerank-001",
            queue_interval_seconds=0.0,
        ),
    )
    manager = KnowledgeManager(
        base_dir=tmp_path,
        retrieval_runtime=runtime,
        default_top_k=3,
        rerank_enabled=True,
        rerank_top_k=2,
    )
    _make_kb(tmp_path, "kb1", {"doc.txt": "line1\nline2"})

    with (
        patch.object(runtime, "embed", new=AsyncMock(return_value=[[0.1, 0.2]])) as emb,
        patch.object(manager, "_get_existing_store") as mock_store,
    ):
        store = AsyncMock()
        store.query = AsyncMock(
            return_value=[
                {"content": "a", "metadata": {}, "distance": 0.2},
                {"content": "b", "metadata": {}, "distance": 0.1},
            ]
        )
        mock_store.return_value = store

        await manager.semantic_search("kb1", "hello")

    emb.assert_awaited_once_with(["Q: hello"])

    await runtime.stop()
