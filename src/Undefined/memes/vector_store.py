from __future__ import annotations

import asyncio
import logging
from pathlib import Path
import re
from typing import Any, cast

import chromadb

from Undefined.memes.models import MemeRecord

logger = logging.getLogger(__name__)
_WHITESPACE_RE = re.compile(r"\s+")


def _distance_to_score(value: Any) -> float:
    try:
        distance = float(value)
    except (TypeError, ValueError):
        distance = 1.0
    score = 1.0 - distance
    if score < 0.0:
        return 0.0
    if score > 1.0:
        return 1.0
    return round(score, 6)


def _normalize_plain_text(value: Any) -> str:
    text = str(value or "").replace("\x00", " ").strip()
    return _WHITESPACE_RE.sub(" ", text)


class MemeVectorStore:
    def __init__(self, path: str | Path, retrieval_runtime: Any | None) -> None:
        self._retrieval_runtime = retrieval_runtime
        client = chromadb.PersistentClient(path=str(path))
        self._collection = client.get_or_create_collection(
            "memes", metadata={"hnsw:space": "cosine"}
        )

    async def upsert(self, record: MemeRecord) -> None:
        document_text = _normalize_plain_text(record.search_text)
        if self._retrieval_runtime is None or not document_text:
            return
        embeddings = await self._retrieval_runtime.embed([document_text])
        embedding: list[float] = [float(value) for value in embeddings[0]]
        embeddings_payload = cast(Any, [embedding])

        def _run() -> None:
            self._collection.upsert(
                ids=[record.uid],
                embeddings=embeddings_payload,
                documents=[document_text],
                metadatas=[
                    {
                        "uid": record.uid,
                        "enabled": bool(record.enabled),
                        "is_animated": bool(record.is_animated),
                        "use_count": int(record.use_count),
                    }
                ],
            )

        await asyncio.to_thread(_run)

    async def delete(self, uid: str) -> None:
        def _run() -> None:
            self._collection.delete(ids=[uid])

        await asyncio.to_thread(_run)

    async def query(
        self,
        query: str,
        *,
        top_k: int,
        include_disabled: bool = False,
    ) -> list[dict[str, Any]]:
        if self._retrieval_runtime is None or not query.strip():
            return []
        normalized_query = _normalize_plain_text(query)
        if not normalized_query:
            return []
        embeddings = await self._retrieval_runtime.embed([normalized_query])
        embedding = list(embeddings[0])

        def _run() -> dict[str, Any]:
            return cast(
                dict[str, Any],
                self._collection.query(
                    query_embeddings=[embedding],  # type: ignore[arg-type]
                    n_results=top_k,
                    include=["documents", "metadatas", "distances"],
                ),
            )

        raw = await asyncio.to_thread(_run)
        docs: list[str] = (raw.get("documents") or [[]])[0]
        metas: list[dict[str, Any]] = (raw.get("metadatas") or [[]])[0]
        dists: list[float] = (raw.get("distances") or [[]])[0]
        items: list[dict[str, Any]] = []
        for document, metadata, distance in zip(docs, metas, dists):
            meta = metadata if isinstance(metadata, dict) else {}
            enabled = bool(meta.get("enabled", True))
            if not include_disabled and not enabled:
                continue
            items.append(
                {
                    "uid": str(meta.get("uid") or ""),
                    "document": str(document or ""),
                    "metadata": meta,
                    "distance": float(distance),
                    "semantic_score": _distance_to_score(distance),
                }
            )
        return items
