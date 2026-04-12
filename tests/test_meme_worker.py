from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from Undefined.memes.worker import MemeWorker


class _FakeQueue:
    def __init__(
        self,
        jobs: list[tuple[str, dict[str, Any]]] | None = None,
        *,
        fail_once: bool = False,
    ) -> None:
        self._jobs = list(jobs or [])
        self._fail_once = fail_once
        self.dequeue_calls = 0
        self.completed: list[str] = []
        self.requeued: list[tuple[str, str]] = []
        self.failed: list[tuple[str, str]] = []

    async def dequeue(self) -> tuple[str, dict[str, Any]] | None:
        self.dequeue_calls += 1
        if self._fail_once:
            self._fail_once = False
            raise RuntimeError("queue boom")
        if self._jobs:
            return self._jobs.pop(0)
        return None

    async def complete(self, job_id: str) -> None:
        self.completed.append(job_id)

    async def requeue(self, job_id: str, error: str) -> None:
        self.requeued.append((job_id, error))

    async def fail(self, job_id: str, error: str) -> None:
        self.failed.append((job_id, error))


@pytest.mark.asyncio
async def test_meme_worker_respects_max_concurrency() -> None:
    queue = _FakeQueue(
        [
            ("job-1", {"kind": "ingest"}),
            ("job-2", {"kind": "ingest"}),
            ("job-3", {"kind": "ingest"}),
        ]
    )
    current = 0
    max_seen = 0

    async def _process_job(_job: dict[str, Any]) -> None:
        nonlocal current, max_seen
        current += 1
        max_seen = max(max_seen, current)
        await asyncio.sleep(0.05)
        current -= 1

    worker = MemeWorker(
        job_queue=queue,
        meme_service=SimpleNamespace(process_job=_process_job),
        poll_interval_seconds=0.01,
        max_retries=0,
        max_concurrency=1,
    )

    await worker.start()
    await asyncio.sleep(0.25)
    await worker.stop()

    assert max_seen == 1
    assert queue.completed == ["job-1", "job-2", "job-3"]


@pytest.mark.asyncio
async def test_meme_worker_handles_dequeue_errors_without_exiting() -> None:
    queue = _FakeQueue(fail_once=True)
    processed: list[dict[str, Any]] = []

    async def _process_job(job: dict[str, Any]) -> None:
        processed.append(job)

    worker = MemeWorker(
        job_queue=queue,
        meme_service=SimpleNamespace(process_job=_process_job),
        poll_interval_seconds=0.01,
        max_retries=0,
        max_concurrency=1,
    )

    await worker.start()
    await asyncio.sleep(0.12)
    await worker.stop()

    assert queue.dequeue_calls >= 2
    assert processed == []
