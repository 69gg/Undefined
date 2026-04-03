from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)


class MemeWorker:
    def __init__(
        self,
        *,
        job_queue: Any,
        meme_service: Any,
        poll_interval_seconds: float = 1.0,
        max_retries: int = 3,
    ) -> None:
        self._job_queue = job_queue
        self._meme_service = meme_service
        self._poll_interval_seconds = max(0.1, float(poll_interval_seconds))
        self._max_retries = max(0, int(max_retries))
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._inflight_tasks: set[asyncio.Task[None]] = set()

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._poll_loop())
        logger.info("[memes] worker started")

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task is not None:
            await self._task
        if self._inflight_tasks:
            await asyncio.gather(*list(self._inflight_tasks), return_exceptions=True)
        logger.info("[memes] worker stopped")

    async def _poll_loop(self) -> None:
        while not self._stop_event.is_set():
            result = await self._job_queue.dequeue()
            if result is None:
                await asyncio.sleep(self._poll_interval_seconds)
                continue
            job_id, job = result
            task = asyncio.create_task(self._process_job(job_id, job))
            self._inflight_tasks.add(task)
            task.add_done_callback(self._inflight_tasks.discard)

    async def _process_job(self, job_id: str, job: dict[str, Any]) -> None:
        retry_count = int(job.get("_retry_count", 0) or 0)
        try:
            await self._meme_service.process_job(job)
        except Exception as exc:
            if retry_count < self._max_retries:
                await self._job_queue.requeue(job_id, str(exc))
                logger.warning(
                    "[memes] job requeued: job_id=%s retry=%s err=%s",
                    job_id,
                    retry_count + 1,
                    exc,
                )
            else:
                await self._job_queue.fail(job_id, str(exc))
                logger.exception("[memes] job failed: job_id=%s", job_id)
            return
        await self._job_queue.complete(job_id)
