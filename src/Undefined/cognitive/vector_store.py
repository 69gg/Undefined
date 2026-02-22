"""ChromaDB 封装，管理 cognitive_events 和 cognitive_profiles 两个 collection。"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import chromadb


class CognitiveVectorStore:
    def __init__(self, path: str | Path, embedder: Any) -> None:
        client = chromadb.PersistentClient(path=str(path))
        self._events = client.get_or_create_collection(
            "cognitive_events", metadata={"hnsw:space": "cosine"}
        )
        self._profiles = client.get_or_create_collection(
            "cognitive_profiles", metadata={"hnsw:space": "cosine"}
        )
        self._embedder = embedder

    async def _embed(self, text: str) -> list[float]:
        results = await self._embedder.embed([text])
        return list(results[0])

    async def upsert_event(
        self, event_id: str, document: str, metadata: dict[str, Any]
    ) -> None:
        emb = await self._embed(document)
        col = self._events
        await asyncio.to_thread(
            lambda: col.upsert(
                ids=[event_id],
                documents=[document],
                embeddings=[emb],  # type: ignore[arg-type]
                metadatas=[metadata],
            )
        )

    async def query_events(
        self,
        query_text: str,
        top_k: int,
        where: dict[str, Any] | None = None,
        reranker: Any = None,
        candidate_multiplier: int = 3,
    ) -> list[dict[str, Any]]:
        return await self._query(
            self._events, query_text, top_k, where, reranker, candidate_multiplier
        )

    async def upsert_profile(
        self, profile_id: str, document: str, metadata: dict[str, Any]
    ) -> None:
        emb = await self._embed(document)
        col = self._profiles
        await asyncio.to_thread(
            lambda: col.upsert(
                ids=[profile_id],
                documents=[document],
                embeddings=[emb],  # type: ignore[arg-type]
                metadatas=[metadata],
            )
        )

    async def query_profiles(
        self,
        query_text: str,
        top_k: int,
        where: dict[str, Any] | None = None,
        reranker: Any = None,
        candidate_multiplier: int = 3,
    ) -> list[dict[str, Any]]:
        return await self._query(
            self._profiles, query_text, top_k, where, reranker, candidate_multiplier
        )

    async def _query(
        self,
        col: Any,
        query_text: str,
        top_k: int,
        where: dict[str, Any] | None,
        reranker: Any,
        candidate_multiplier: int,
    ) -> list[dict[str, Any]]:
        emb = await self._embed(query_text)
        fetch_k = top_k * candidate_multiplier if reranker else top_k
        kwargs: dict[str, Any] = dict(
            query_embeddings=[emb],
            n_results=fetch_k,
            include=["documents", "metadatas", "distances"],
        )
        if where:
            kwargs["where"] = where

        def _q() -> Any:
            return col.query(**kwargs)

        raw = await asyncio.to_thread(_q)
        docs: list[str] = (raw.get("documents") or [[]])[0]
        metas: list[dict[str, Any]] = (raw.get("metadatas") or [[]])[0]
        dists: list[float] = (raw.get("distances") or [[]])[0]
        results = [
            {"document": d, "metadata": m, "distance": dist}
            for d, m, dist in zip(docs, metas, dists)
        ]

        if reranker and results:
            reranked = await reranker.rerank(
                query_text, [r["document"] for r in results], top_n=top_k
            )
            return [
                {
                    "document": r["document"],
                    "metadata": results[r["index"]]["metadata"],
                    "distance": results[r["index"]]["distance"],
                }
                for r in reranked[:top_k]
            ]
        return results[:top_k]
