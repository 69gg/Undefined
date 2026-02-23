"""统一检索运行时：管理 Embedder / Reranker 的初始化与生命周期。"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from Undefined.knowledge.embedder import Embedder
from Undefined.knowledge.reranker import Reranker

if TYPE_CHECKING:
    from Undefined.ai.llm import ModelRequester
    from Undefined.config.models import EmbeddingModelConfig, RerankModelConfig

logger = logging.getLogger(__name__)


class RetrievalRuntime:
    """统一管理嵌入与重排能力。

    - 嵌入与重排均通过各自队列发车（Embedder / Reranker 内部实现）。
    - 发车频率由 `models.embedding.queue_interval_seconds` /
      `models.rerank.queue_interval_seconds` 控制。
    - 复用同一 `ModelRequester`，确保统一 OpenAI SDK 客户端与 token 统计口径。
    """

    def __init__(
        self,
        model_requester: ModelRequester,
        embedding_model: EmbeddingModelConfig,
        rerank_model: RerankModelConfig,
        *,
        embed_batch_size: int = 64,
    ) -> None:
        self._requester = model_requester
        self._embedding_model = embedding_model
        self._rerank_model = rerank_model
        self._embed_batch_size = int(embed_batch_size)
        self._embedder: Embedder | None = None
        self._reranker: Reranker | None = None

    @property
    def rerank_model_ready(self) -> bool:
        return bool(self._rerank_model.api_url and self._rerank_model.model_name)

    def ensure_embedder(self) -> Embedder:
        embedder = self._embedder
        if embedder is None:
            embedder = Embedder(
                self._requester,
                self._embedding_model,
                batch_size=self._embed_batch_size,
            )
            embedder.start()
            self._embedder = embedder
            logger.info(
                "[检索运行时] 嵌入发车器已启动: interval=%.2fs batch_size=%s model=%s",
                embedder.interval,
                self._embed_batch_size,
                self._embedding_model.model_name,
            )
        return embedder

    @property
    def query_instruction(self) -> str:
        return str(getattr(self._embedding_model, "query_instruction", "") or "")

    @property
    def document_instruction(self) -> str:
        return str(getattr(self._embedding_model, "document_instruction", "") or "")

    async def embed(self, texts: list[str]) -> list[list[float]]:
        embedder = self.ensure_embedder()
        return await embedder.embed(texts)

    def ensure_reranker(self) -> Reranker | None:
        if not self.rerank_model_ready:
            return None
        reranker = self._reranker
        if reranker is None:
            reranker = Reranker(self._requester, self._rerank_model)
            reranker.start()
            self._reranker = reranker
            logger.info(
                "[检索运行时] 重排发车器已启动: interval=%.2fs model=%s",
                reranker.interval,
                self._rerank_model.model_name,
            )
        return reranker

    async def rerank(
        self,
        query: str,
        documents: list[str],
        top_n: int | None = None,
    ) -> list[dict[str, object]]:
        reranker = self.ensure_reranker()
        if reranker is None:
            return []
        return await reranker.rerank(query=query, documents=documents, top_n=top_n)

    async def stop(self) -> None:
        if self._reranker is not None:
            await self._reranker.stop()
            self._reranker = None
        if self._embedder is not None:
            await self._embedder.stop()
            self._embedder = None
