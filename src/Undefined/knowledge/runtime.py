"""统一检索运行时：管理 Embedder / Reranker 的初始化与生命周期。"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
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
        reranker_provider: Callable[[], Reranker | None] | None = None,
    ) -> None:
        self._requester = model_requester
        self._embedding_model = embedding_model
        self._rerank_model = rerank_model
        self._embed_batch_size = int(embed_batch_size)
        # 多运行时（按功能拆分 embedding）时由注册表提供共享重排器
        self._reranker_provider = reranker_provider
        self._embedder: Embedder | None = None
        self._reranker: Reranker | None = None

    @property
    def embedding_model(self) -> EmbeddingModelConfig:
        return self._embedding_model

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
        if self._reranker_provider is not None:
            return self._reranker_provider()
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


class RetrievalRuntimeRegistry:
    """按功能解析 embedding 配置并管理 `RetrievalRuntime` 生命周期。

    - 每个功能（`EMBEDDING_FEATURES`，如 knowledge / cognitive / memes）取
      `Config.resolve_embedding_model(feature)` 的实际生效配置；
    - 生效配置完全相同的功能共用同一个运行时（包括发车队列），避免重复建连
      与重复限速；任一字段不同时该功能拥有独立的 Embedder 与队列；
    - 重排模型在所有功能之间共享。
    """

    def __init__(
        self,
        model_requester: ModelRequester,
        *,
        embedding_models: Mapping[str, EmbeddingModelConfig],
        rerank_model: RerankModelConfig,
        embed_batch_size: int = 64,
    ) -> None:
        self._requester = model_requester
        self._embedding_models = dict(embedding_models)
        self._rerank_model = rerank_model
        self._embed_batch_size = int(embed_batch_size)
        self._runtimes: list[RetrievalRuntime] = []
        self._reranker: Reranker | None = None
        self._reranker_initialized = False

    def for_feature(self, feature: str) -> RetrievalRuntime:
        """返回功能对应的检索运行时；相同生效配置复用同一实例。"""
        model = self._embedding_models.get(feature)
        if model is None:
            raise KeyError(f"unknown embedding feature: {feature}")
        for runtime in self._runtimes:
            if runtime.embedding_model == model:
                return runtime
        runtime = RetrievalRuntime(
            self._requester,
            model,
            self._rerank_model,
            embed_batch_size=self._embed_batch_size,
            reranker_provider=self.ensure_reranker,
        )
        self._runtimes.append(runtime)
        logger.info(
            "[检索运行时] 功能已绑定 embedding 配置: feature=%s model=%s interval=%.2fs",
            feature,
            model.model_name,
            model.queue_interval_seconds,
        )
        return runtime

    @property
    def runtimes(self) -> tuple[RetrievalRuntime, ...]:
        return tuple(self._runtimes)

    def ensure_reranker(self) -> Reranker | None:
        """共享重排器；未配置完整时返回 None。"""
        if not self._reranker_initialized:
            self._reranker_initialized = True
            if self._rerank_model.api_url and self._rerank_model.model_name:
                reranker = Reranker(self._requester, self._rerank_model)
                reranker.start()
                self._reranker = reranker
                logger.info(
                    "[检索运行时] 重排发车器已启动: interval=%.2fs model=%s",
                    reranker.interval,
                    self._rerank_model.model_name,
                )
        return self._reranker

    async def stop(self) -> None:
        if self._reranker is not None:
            await self._reranker.stop()
            self._reranker = None
        self._reranker_initialized = False
        for runtime in self._runtimes:
            await runtime.stop()
        self._runtimes.clear()
