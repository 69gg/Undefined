"""ChromaDB 封装，管理 cognitive_events 和 cognitive_profiles 两个 collection。"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import chromadb
import numpy as np
from numba import njit
from numpy.typing import NDArray

logger = logging.getLogger(__name__)


def _clamp(value: float, lower: float, upper: float) -> float:
    if value < lower:
        return lower
    if value > upper:
        return upper
    return value


def _safe_float(value: Any, default: float = 0.0) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except Exception:
            return default
    return default


def _safe_positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except Exception:
        return max(1, int(default))
    if parsed <= 0:
        return max(1, int(default))
    return parsed


def _metadata_timestamp_epoch(metadata: Any) -> float | None:
    if not isinstance(metadata, dict):
        return None
    raw_epoch = metadata.get("timestamp_epoch")
    if isinstance(raw_epoch, (int, float)):
        return float(raw_epoch)
    if isinstance(raw_epoch, str):
        try:
            return float(raw_epoch.strip())
        except Exception:
            pass

    for key in ("timestamp_utc", "timestamp_local"):
        raw_text = metadata.get(key)
        if not isinstance(raw_text, str):
            continue
        text = raw_text.strip()
        if not text:
            continue
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return float(parsed.timestamp())
        except Exception:
            continue
    return None


def _similarity_from_distance(distance: Any) -> float:
    dist = _safe_float(distance, default=1.0)
    return _clamp(1.0 - dist, 0.0, 1.0)


@njit(cache=True)  # type: ignore[untyped-decorator]
def _mmr_select(
    embeddings: NDArray[np.float32],
    query_embedding: NDArray[np.float32],
    top_k: int,
    lambda_param: float,
) -> NDArray[np.intp]:
    """MMR 贪心选择，返回选中的索引数组。"""
    n = embeddings.shape[0]
    if n <= top_k:
        return np.arange(n)

    # 预计算 query-doc 相关性（cosine similarity）
    query_norm = np.sqrt(np.sum(query_embedding * query_embedding))
    relevance = np.empty(n, dtype=np.float64)
    norms = np.empty(n, dtype=np.float64)
    for i in range(n):
        norms[i] = np.sqrt(np.sum(embeddings[i] * embeddings[i]))
        if query_norm == 0.0 or norms[i] == 0.0:
            relevance[i] = 0.0
        else:
            relevance[i] = np.sum(embeddings[i] * query_embedding) / (
                norms[i] * query_norm
            )

    selected = np.empty(top_k, dtype=np.intp)
    max_sim_to_selected = np.full(n, -np.inf, dtype=np.float64)
    chosen = np.zeros(n, dtype=np.bool_)

    for step in range(top_k):
        best_idx = -1
        best_score = -np.inf
        for i in range(n):
            if chosen[i]:
                continue
            redundancy = max(max_sim_to_selected[i], 0.0) if step > 0 else 0.0
            score = lambda_param * relevance[i] - (1.0 - lambda_param) * redundancy
            if score > best_score:
                best_score = score
                best_idx = i
        if best_idx < 0:
            return selected[:step]
        selected[step] = best_idx
        chosen[best_idx] = True
        # 更新 max_sim_to_selected：新选中项与所有未选中项的相似度
        if norms[best_idx] > 0.0:
            for j in range(n):
                if not chosen[j] and norms[j] > 0.0:
                    sim = np.sum(embeddings[j] * embeddings[best_idx]) / (
                        norms[j] * norms[best_idx]
                    )
                    if sim > max_sim_to_selected[j]:
                        max_sim_to_selected[j] = sim

    return selected


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
        time_decay_enabled: bool = False,
        time_decay_half_life_days: float = 14.0,
        time_decay_boost: float = 0.2,
        time_decay_min_similarity: float = 0.35,
        apply_mmr: bool = False,
    ) -> list[dict[str, Any]]:
        logger.info(
            "[认知向量库] 查询事件: query_len=%s top_k=%s where=%s reranker=%s multiplier=%s decay_enabled=%s half_life_days=%s boost=%s min_sim=%s mmr=%s",
            len(query_text or ""),
            top_k,
            where or {},
            bool(reranker),
            candidate_multiplier,
            time_decay_enabled,
            time_decay_half_life_days,
            time_decay_boost,
            time_decay_min_similarity,
            apply_mmr,
        )
        return await self._query(
            self._events,
            query_text,
            top_k,
            where,
            reranker,
            candidate_multiplier,
            apply_time_decay=time_decay_enabled,
            time_decay_half_life_days=time_decay_half_life_days,
            time_decay_boost=time_decay_boost,
            time_decay_min_similarity=time_decay_min_similarity,
            apply_mmr=apply_mmr,
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
        *,
        apply_time_decay: bool = False,
        time_decay_half_life_days: float = 14.0,
        time_decay_boost: float = 0.2,
        time_decay_min_similarity: float = 0.35,
        apply_mmr: bool = False,
    ) -> list[dict[str, Any]]:
        col_name = getattr(col, "name", "unknown")
        safe_top_k = _safe_positive_int(top_k, default=1)
        safe_multiplier = _safe_positive_int(candidate_multiplier, default=1)
        logger.debug(
            "[认知向量库] 开始查询 collection=%s top_k=%s where=%s decay=%s mmr=%s",
            col_name,
            safe_top_k,
            where or {},
            apply_time_decay,
            apply_mmr,
        )
        emb = await self._embed(query_text)
        # 重排要求候选数 > 最终返回数，否则重排无意义
        use_reranker = bool(reranker) and safe_multiplier >= 2
        if reranker and safe_multiplier < 2:
            logger.warning(
                "[认知记忆] rerank_candidate_multiplier=%s < 2，跳过重排",
                safe_multiplier,
            )
        use_extra_candidates = safe_multiplier >= 2 and (
            use_reranker or apply_time_decay or apply_mmr
        )
        fetch_k = safe_top_k * safe_multiplier if use_extra_candidates else safe_top_k
        include: list[str] = ["documents", "metadatas", "distances"]
        if apply_mmr:
            include.append("embeddings")
        kwargs: dict[str, Any] = dict(
            query_embeddings=[emb],
            n_results=fetch_k,
            include=include,
        )
        if where:
            kwargs["where"] = where

        def _q() -> Any:
            return col.query(**kwargs)

        raw = await asyncio.to_thread(_q)
        docs: list[str] = (raw.get("documents") or [[]])[0]
        metas: list[dict[str, Any]] = (raw.get("metadatas") or [[]])[0]
        dists: list[float] = (raw.get("distances") or [[]])[0]
        embeddings_raw: list[list[float]] = (
            (raw.get("embeddings") or [[]])[0] if apply_mmr else []
        )
        results: list[dict[str, Any]] = []
        for i, (d, m, dist) in enumerate(zip(docs, metas, dists)):
            item: dict[str, Any] = {"document": d, "metadata": m, "distance": dist}
            if apply_mmr and i < len(embeddings_raw):
                item["embedding"] = embeddings_raw[i]
            results.append(item)
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
                safe_top_k,
            )
            rerank_top_n = fetch_k if (apply_time_decay or apply_mmr) else safe_top_k
            reranked = await reranker.rerank(
                query_text, [r["document"] for r in results], top_n=rerank_top_n
            )
            reranked_results: list[dict[str, Any]] = []
            for item in reranked[:rerank_top_n]:
                index = int(_safe_float(item.get("index"), default=-1))
                if index < 0 or index >= len(results):
                    continue
                entry: dict[str, Any] = {
                    "document": item.get("document", results[index]["document"]),
                    "metadata": results[index]["metadata"],
                    "distance": results[index]["distance"],
                    "rerank_score": _safe_float(
                        item.get("relevance_score"), default=0.0
                    ),
                }
                if apply_mmr and "embedding" in results[index]:
                    entry["embedding"] = results[index]["embedding"]
                reranked_results.append(entry)
            logger.info(
                "[认知向量库] 重排完成: collection=%s final_count=%s",
                col_name,
                len(reranked_results),
            )
            results = reranked_results

        if apply_time_decay and results:
            decay_top_k = fetch_k if apply_mmr else safe_top_k
            final = self._apply_time_decay_ranking(
                results=results,
                top_k=decay_top_k,
                half_life_days=time_decay_half_life_days,
                boost=time_decay_boost,
                min_similarity=time_decay_min_similarity,
                collection_name=col_name,
            )
            logger.info(
                "[认知向量库] 时间衰减重排完成: collection=%s final_count=%s",
                col_name,
                len(final),
            )
        else:
            final = results if apply_mmr else results[:safe_top_k]

        if apply_mmr and final:
            final = self._apply_mmr(final, emb, safe_top_k)
            for item in final:
                item.pop("embedding", None)

        logger.info(
            "[认知向量库] 返回查询结果: collection=%s final_count=%s",
            col_name,
            len(final),
        )
        return final

    def _apply_time_decay_ranking(
        self,
        *,
        results: list[dict[str, Any]],
        top_k: int,
        half_life_days: float,
        boost: float,
        min_similarity: float,
        collection_name: str,
    ) -> list[dict[str, Any]]:
        safe_top_k = max(1, int(top_k))
        safe_half_life_days = _safe_float(half_life_days, default=14.0)
        safe_boost = max(0.0, _safe_float(boost, default=0.2))
        safe_min_similarity = _clamp(
            _safe_float(min_similarity, default=0.35), 0.0, 1.0
        )
        if safe_half_life_days <= 0:
            logger.warning(
                "[认知向量库] 时间衰减参数非法，跳过时间加权: collection=%s half_life_days=%s",
                collection_name,
                safe_half_life_days,
            )
            return results[:safe_top_k]

        half_life_seconds = safe_half_life_days * 86400.0
        now_epoch = datetime.now(timezone.utc).timestamp()
        scored: list[tuple[float, float, float, int, dict[str, Any]]] = []
        for index, item in enumerate(results):
            similarity = _similarity_from_distance(item.get("distance"))
            ts_epoch = _metadata_timestamp_epoch(item.get("metadata"))
            if ts_epoch is None:
                age_seconds = None
                decay = 0.0
            else:
                age_seconds = max(0.0, now_epoch - ts_epoch)
                decay = 0.5 ** (age_seconds / half_life_seconds)
            multiplier = 1.0
            if similarity >= safe_min_similarity:
                multiplier += safe_boost * decay
            final_score = similarity * multiplier
            ts_sort = ts_epoch if ts_epoch is not None else float("-inf")
            scored.append((final_score, similarity, ts_sort, index, item))
            logger.debug(
                "[认知向量库] 时间加权候选: collection=%s idx=%s sim=%.6f decay=%.6f multiplier=%.6f score=%.6f age_seconds=%s",
                collection_name,
                index,
                similarity,
                decay,
                multiplier,
                final_score,
                f"{age_seconds:.3f}" if age_seconds is not None else "None",
            )

        scored.sort(key=lambda it: (-it[0], -it[1], -it[2], it[3]))
        final = [item for _, _, _, _, item in scored[:safe_top_k]]
        if scored:
            logger.info(
                "[认知向量库] 时间加权摘要: collection=%s candidates=%s top_score=%.6f half_life_days=%s boost=%s min_sim=%s",
                collection_name,
                len(scored),
                scored[0][0],
                safe_half_life_days,
                safe_boost,
                safe_min_similarity,
            )
        return final

    @staticmethod
    def _apply_mmr(
        results: list[dict[str, Any]],
        query_embedding: list[float],
        top_k: int,
        lambda_param: float = 0.7,
    ) -> list[dict[str, Any]]:
        """MMR 多样性筛选，从候选集中选出语义多样的 top_k 条。"""
        if len(results) <= top_k:
            return results
        valid = [r for r in results if "embedding" in r]
        if len(valid) <= top_k:
            return results[:top_k]
        emb_matrix = np.array([r["embedding"] for r in valid], dtype=np.float32)
        q_emb = np.array(query_embedding, dtype=np.float32)
        indices = _mmr_select(emb_matrix, q_emb, top_k, lambda_param)
        return [valid[int(i)] for i in indices]
