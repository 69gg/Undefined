"""ChromaDB 存储管理"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from pathlib import Path
from typing import Any

import chromadb

logger = logging.getLogger(__name__)


class KnowledgeStore:
    """管理单个知识库的 ChromaDB collection。"""

    def __init__(self, name: str, chroma_dir: Path) -> None:
        self.name = name
        self._client = chromadb.PersistentClient(path=str(chroma_dir))
        self._collection = self._client.get_or_create_collection(
            name=name,
            metadata={"hnsw:space": "cosine"},
        )

    def _content_hash(self, text: str) -> str:
        return hashlib.sha256(text.encode()).hexdigest()[:16]

    async def add_chunks(
        self,
        chunks: list[str],
        embeddings: list[list[float]],
        metadata_base: dict[str, Any] | None = None,
    ) -> int:
        if not chunks:
            return 0
        ids = [self._content_hash(c) for c in chunks]
        metadatas: list[dict[str, Any]] = [
            {**(metadata_base or {}), "chunk_index": i} for i in range(len(chunks))
        ]

        def _upsert() -> None:
            self._collection.upsert(
                ids=ids,
                embeddings=embeddings,  # type: ignore[arg-type]
                documents=chunks,
                metadatas=metadatas,  # type: ignore[arg-type]
            )

        await asyncio.to_thread(_upsert)
        return len(chunks)

    async def query(
        self, query_embedding: list[float], top_k: int = 5
    ) -> list[dict[str, Any]]:
        def _query() -> dict[str, Any]:
            return self._collection.query(  # type: ignore[return-value]
                query_embeddings=[query_embedding],  # type: ignore[arg-type]
                n_results=top_k,
                include=["documents", "metadatas", "distances"],
            )

        raw = await asyncio.to_thread(_query)
        docs: list[str] = (raw.get("documents") or [[]])[0]
        metas: list[dict[str, Any]] = (raw.get("metadatas") or [[]])[0]
        dists: list[float] = (raw.get("distances") or [[]])[0]
        return [
            {"content": d, "metadata": m, "distance": dist}
            for d, m, dist in zip(docs, metas, dists)
        ]
