from __future__ import annotations

import asyncio
import os
import time
from collections.abc import Collection
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from Undefined.memes.worker import MemeWorker
from Undefined.cognitive.job_queue import JobQueue


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

    async def recover_stale(
        self, timeout_seconds: float, *, exclude_job_ids: Collection[str] = ()
    ) -> int:
        return 0


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


@pytest.mark.asyncio
async def test_meme_worker_recovers_fast_restart_orphan_after_it_becomes_stale(
    tmp_path: Path,
) -> None:
    previous_queue = JobQueue(tmp_path)
    orphan = await previous_queue.enqueue({"marker": "orphan"})
    assert await previous_queue.dequeue() is not None
    queue = JobQueue(tmp_path)
    processed: list[str] = []
    orphan_processed = asyncio.Event()

    async def process_job(job: dict[str, Any]) -> None:
        processed.append(str(job["marker"]))
        if job["marker"] == "orphan":
            orphan_processed.set()

    worker = MemeWorker(
        job_queue=queue,
        meme_service=SimpleNamespace(process_job=process_job),
        poll_interval_seconds=0.1,
    )
    await worker.start()
    try:
        assert queue.snapshot()["processing"] == 1
        await queue.enqueue({"marker": "fresh"})
        stamp = time.time() - 301
        os.utime(tmp_path / "processing" / f"{orphan}.json", (stamp, stamp))
        await asyncio.wait_for(orphan_processed.wait(), timeout=2)
    finally:
        await worker.stop()
    assert sorted(processed) == ["fresh", "orphan"]
    assert queue.snapshot()["processing"] == queue.snapshot()["pending"] == 0


@pytest.mark.asyncio
async def test_meme_worker_does_not_recover_active_long_running_job(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue = JobQueue(tmp_path)
    job_id = await queue.enqueue({"marker": "active"})
    started = asyncio.Event()
    release = asyncio.Event()
    checked = asyncio.Event()
    calls: list[str] = []
    real_recover = queue.recover_stale

    async def recover_stale(
        timeout_seconds: float, *, exclude_job_ids: Collection[str] = ()
    ) -> int:
        recovered = await real_recover(timeout_seconds, exclude_job_ids=exclude_job_ids)
        if started.is_set() and not release.is_set():
            assert job_id in exclude_job_ids
            assert recovered == 0
            checked.set()
        return recovered

    async def process_job(job: dict[str, Any]) -> None:
        calls.append(str(job["marker"]))
        started.set()
        await release.wait()

    monkeypatch.setattr(queue, "recover_stale", recover_stale)
    worker = MemeWorker(
        job_queue=queue,
        meme_service=SimpleNamespace(process_job=process_job),
        max_concurrency=1,
        poll_interval_seconds=0.1,
    )
    await worker.start()
    try:
        await asyncio.wait_for(started.wait(), timeout=2)
        stamp = time.time() - 301
        os.utime(tmp_path / "processing" / f"{job_id}.json", (stamp, stamp))
        await asyncio.wait_for(checked.wait(), timeout=2)
        assert queue.snapshot()["processing"] == 1
        assert queue.snapshot()["pending"] == 0
        assert calls == ["active"]
    finally:
        release.set()
        await worker.stop()
    assert not worker._active_jobs


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["cancel", "complete"])
async def test_meme_worker_recovers_job_after_task_did_not_complete(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    queue = JobQueue(tmp_path)
    await queue.enqueue({"marker": "retry"})
    processed = 0
    finished = asyncio.Event()
    real_complete = queue.complete
    complete_calls = 0

    async def process_job(job: dict[str, Any]) -> None:
        nonlocal processed
        processed += 1
        if failure == "cancel" and processed == 1:
            raise asyncio.CancelledError

    async def complete(job_id: str) -> None:
        nonlocal complete_calls
        complete_calls += 1
        if failure == "complete" and complete_calls == 1:
            raise OSError("isolated completion failure")
        await real_complete(job_id)
        finished.set()

    monkeypatch.setattr(queue, "complete", complete)
    worker = MemeWorker(
        job_queue=queue,
        meme_service=SimpleNamespace(process_job=process_job),
        stale_job_timeout_seconds=0,
        poll_interval_seconds=0.1,
    )
    await worker.start()
    try:
        await asyncio.wait_for(finished.wait(), timeout=2)
    finally:
        await worker.stop()
    assert processed == 2
    assert not worker._active_jobs
    assert queue.snapshot()["processing"] == 0
