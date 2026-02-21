"""嵌入请求封装：站台/发车队列 + 分批。"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from Undefined.ai.llm import ModelRequester
    from Undefined.config.models import EmbeddingModelConfig

logger = logging.getLogger(__name__)


@dataclass
class _EmbedJob:
    texts: list[str]
    future: asyncio.Future[list[list[float]]] = field(
        default_factory=lambda: asyncio.get_event_loop().create_future()
    )


class Embedder:
    """通过站台/发车队列调用嵌入 API，支持分批。"""

    def __init__(
        self,
        model_requester: ModelRequester,
        model_config: EmbeddingModelConfig,
        batch_size: int = 64,
    ) -> None:
        self._requester = model_requester
        self._config = model_config
        self._batch_size = batch_size
        self._queue: asyncio.Queue[_EmbedJob] = asyncio.Queue()
        self._task: asyncio.Task[None] | None = None

    @property
    def interval(self) -> float:
        return float(getattr(self._config, "queue_interval_seconds", 1.0))

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._process_loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            self._task = None

    async def _process_loop(self) -> None:
        """站台/发车：按固定间隔从队列取任务并执行。"""
        while True:
            job = await self._queue.get()
            try:
                result = await self._requester.embed(self._config, job.texts)
                job.future.set_result(result)
            except Exception as exc:
                if not job.future.done():
                    job.future.set_exception(exc)
            await asyncio.sleep(self.interval)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """分批提交嵌入请求，通过队列排队执行。"""
        if not texts:
            return []
        all_embeddings: list[list[float]] = []
        for i in range(0, len(texts), self._batch_size):
            batch = texts[i : i + self._batch_size]
            job = _EmbedJob(texts=batch)
            await self._queue.put(job)
            result = await job.future
            all_embeddings.extend(result)
        return all_embeddings
