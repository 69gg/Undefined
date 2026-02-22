"""重排请求封装：站台/发车队列。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from Undefined.ai.llm import ModelRequester
    from Undefined.config.models import RerankModelConfig


def _create_future() -> asyncio.Future[list[dict[str, Any]]]:
    return asyncio.get_running_loop().create_future()


@dataclass
class _RerankJob:
    query: str
    documents: list[str]
    top_n: int | None
    future: asyncio.Future[list[dict[str, Any]]] = field(default_factory=_create_future)


class Reranker:
    """通过站台/发车队列调用重排 API。"""

    def __init__(
        self,
        model_requester: ModelRequester,
        model_config: RerankModelConfig,
    ) -> None:
        self._requester = model_requester
        self._config = model_config
        self._queue: asyncio.Queue[_RerankJob] = asyncio.Queue()
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
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _process_loop(self) -> None:
        while True:
            job = await self._queue.get()
            try:
                result = await self._requester.rerank(
                    model_config=self._config,
                    query=job.query,
                    documents=job.documents,
                    top_n=job.top_n,
                )
                if not job.future.done():
                    job.future.set_result(result)
            except Exception as exc:
                if not job.future.done():
                    job.future.set_exception(exc)
            await asyncio.sleep(self.interval)

    async def rerank(
        self,
        query: str,
        documents: list[str],
        top_n: int | None = None,
    ) -> list[dict[str, Any]]:
        if not documents:
            return []
        job = _RerankJob(query=query, documents=documents, top_n=top_n)
        await self._queue.put(job)
        return await job.future
