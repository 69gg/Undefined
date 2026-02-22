"""ChromaDB 封装，管理 cognitive_events 和 cognitive_profiles 两个 collection。"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

import chromadb

logger = logging.getLogger(__name__)


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
        logger.info(
            "[认知向量库] 初始化完成: path=%s events=%s profiles=%s",
            str(path),
            getattr(self._events, "name", "cognitive_events"),
            getattr(self._profiles, "name", "cognitive_profiles"),
        )

    async def _embed(self, text: str) -> list[float]:
        results = await self._embedder.embed([text])
        vector = list(results[0])
        logger.debug(
            "[认知向量库] 向量化完成: text_len=%s dim=%s",
            len(text or ""),
            len(vector),
        )
        return vector

    async def upsert_event(
        self, event_id: str, document: str, metadata: dict[str, Any]
    ) -> None:
        logger.info(
            "[认知向量库] 写入事件: event_id=%s doc_len=%s metadata_keys=%s",
            event_id,
            len(document or ""),
            sorted(metadata.keys()),
        )
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
        logger.info("[认知向量库] 事件写入完成: event_id=%s", event_id)

    async def query_events(
        self,
        query_text: str,
        top_k: int,
        where: dict[str, Any] | None = None,
        reranker: Any = None,
        candidate_multiplier: int = 3,
    ) -> list[dict[str, Any]]:
        logger.info(
            "[认知向量库] 查询事件: query_len=%s top_k=%s where=%s reranker=%s multiplier=%s",
            len(query_text or ""),
            top_k,
            where or {},
            bool(reranker),
            candidate_multiplier,
        )
        return await self._query(
            self._events, query_text, top_k, where, reranker, candidate_multiplier
        )

    async def upsert_profile(
        self, profile_id: str, document: str, metadata: dict[str, Any]
    ) -> None:
        logger.info(
            "[认知向量库] 写入侧写向量: profile_id=%s doc_len=%s metadata_keys=%s",
            profile_id,
            len(document or ""),
            sorted(metadata.keys()),
        )
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
        logger.info("[认知向量库] 侧写向量写入完成: profile_id=%s", profile_id)

    async def query_profiles(
        self,
        query_text: str,
        top_k: int,
        where: dict[str, Any] | None = None,
        reranker: Any = None,
        candidate_multiplier: int = 3,
    ) -> list[dict[str, Any]]:
        logger.info(
            "[认知向量库] 查询侧写: query_len=%s top_k=%s where=%s reranker=%s multiplier=%s",
            len(query_text or ""),
            top_k,
            where or {},
            bool(reranker),
            candidate_multiplier,
        )
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
        col_name = getattr(col, "name", "unknown")
        logger.debug(
            "[认知向量库] 开始查询 collection=%s top_k=%s where=%s",
            col_name,
            top_k,
            where or {},
        )
        emb = await self._embed(query_text)
        # 重排要求候选数 > 最终返回数，否则重排无意义
        use_reranker = reranker and candidate_multiplier >= 2
        if reranker and candidate_multiplier < 2:
            logger.warning(
                "[认知记忆] rerank_candidate_multiplier=%s < 2，跳过重排",
                candidate_multiplier,
            )
        fetch_k = top_k * candidate_multiplier if use_reranker else top_k
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
        logger.info(
            "[认知向量库] 查询完成: collection=%s fetch_k=%s hit_count=%s",
            col_name,
            fetch_k,
            len(results),
        )

        if use_reranker and results:
            logger.info(
                "[认知向量库] 开始重排: collection=%s candidates=%s top_k=%s",
                col_name,
                len(results),
                top_k,
            )
            reranked = await reranker.rerank(
                query_text, [r["document"] for r in results], top_n=top_k
            )
            final = [
                {
                    "document": r["document"],
                    "metadata": results[r["index"]]["metadata"],
                    "distance": results[r["index"]]["distance"],
                }
                for r in reranked[:top_k]
            ]
            logger.info(
                "[认知向量库] 重排完成: collection=%s final_count=%s",
                col_name,
                len(final),
            )
            return final
        final = results[:top_k]
        logger.info(
            "[认知向量库] 返回查询结果: collection=%s final_count=%s",
            col_name,
            len(final),
        )
        return final
