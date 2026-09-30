from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from typing import Any

import pytest

from Undefined.cognitive.job_queue import JobQueue
from Undefined.utils.io import write_json, write_json_sync


@pytest.mark.asyncio
async def test_enqueue_orders_concurrent_same_request_and_survives_clock_rollback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("Undefined.cognitive.job_queue.time.time_ns", lambda: 100)
    queue = JobQueue(tmp_path)
    ids = await asyncio.gather(
        *[
            queue.enqueue({"request_id": "same", "end_seq": 1, "index": index})
            for index in range(20)
        ]
    )
    assert len(set(ids)) == 20
    entries = await queue.list_jobs()
    assert [item.data["index"] for item in entries] == list(range(20))
    assert [item.data["_enqueue_order"] for item in entries] == list(range(100, 120))
    # 请求 ID 的字典序、时钟回拨及重启均不改变未完成任务的相对顺序。
    restarted = JobQueue(tmp_path)
    monkeypatch.setattr("Undefined.cognitive.job_queue.time.time_ns", lambda: 1)
    last = await restarted.enqueue({"request_id": "a", "index": 20})
    assert (await restarted.list_jobs())[-1].job_id == last
    for expected in ids + [last]:
        item = await restarted.dequeue()
        assert item is not None and item[0] == expected
        await restarted.complete(expected)


@pytest.mark.asyncio
async def test_legacy_jobs_use_enqueue_suffix_then_payload_time(tmp_path: Path) -> None:
    queue = JobQueue(tmp_path)
    await write_json(tmp_path / "pending/z_1_1000.json", {"user_id": "1"})
    await write_json(tmp_path / "pending/a_1_2000.json", {"user_id": "1"})
    await write_json(
        tmp_path / "processing/legacy.json",
        {
            "timestamp_utc": "1970-01-01T00:00:01.500000+00:00",
        },
    )
    assert [entry.job_id for entry in await queue.list_jobs()] == [
        "z_1_1000",
        "legacy",
        "a_1_2000",
    ]


@pytest.mark.asyncio
async def test_stage_retry_and_manual_retry_preserve_progress(tmp_path: Path) -> None:
    queue = JobQueue(tmp_path)
    first = await queue.enqueue({"request_id": "z", "timestamp_epoch": 123})
    second = await queue.enqueue({"request_id": "a"})
    item = await queue.claim(first)
    assert item is not None
    job = item[1]
    original_order = job["_enqueue_order"]
    job["_historian_progress"] = {"rewrites": ["saved"]}
    await queue.checkpoint(first, job)
    await queue.release(first)
    assert (await queue.list_jobs())[0].data.get("_retry_count", 0) == 0
    await queue.claim(first)
    await queue.requeue(first, "temporary")
    entry = (await queue.list_jobs())[0]
    assert entry.data["_retry_count"] == 1
    assert entry.data["_enqueue_order"] == original_order
    assert entry.data["_historian_progress"] == {"rewrites": ["saved"]}
    await queue.claim(first)
    await queue.fail(first, "terminal")
    assert await queue.retry_all() == 1
    entries = await queue.list_jobs()
    assert [entry.job_id for entry in entries] == [second, first]
    assert entries[-1].data["timestamp_epoch"] == 123
    assert entries[-1].data["_retry_count"] == 0
    assert entries[-1].data["_historian_progress"] == {"rewrites": ["saved"]}


@pytest.mark.asyncio
async def test_recovery_excludes_live_jobs_and_keeps_order(tmp_path: Path) -> None:
    queue = JobQueue(tmp_path)
    first = await queue.enqueue({"request_id": "z"})
    second = await queue.enqueue({"request_id": "a"})
    await queue.claim(first)
    await queue.claim(second)
    assert await queue.recover_stale(-1, exclude_job_ids={second}) == 1
    entries = await queue.list_jobs()
    assert [(entry.job_id, entry.state) for entry in entries] == [
        (first, "pending"),
        (second, "processing"),
    ]


@pytest.mark.asyncio
async def test_cancelled_enqueue_waits_for_disk_before_unlocking(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    queue = JobQueue(tmp_path)
    started = asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()

    def blocked_write(path: Path, data: Any, use_lock: bool = True) -> None:
        if data.get("request_id") == "first":
            loop.call_soon_threadsafe(started.set)
            assert release.wait(5)
        write_json_sync(path, data, use_lock)

    monkeypatch.setattr("Undefined.cognitive.job_queue.write_json_sync", blocked_write)
    first = asyncio.create_task(queue.enqueue({"request_id": "first"}))
    second: asyncio.Task[str] | None = None
    try:
        await asyncio.wait_for(started.wait(), 3)
        first.cancel()
        second = asyncio.create_task(queue.enqueue({"request_id": "second"}))
        await asyncio.sleep(0)
        first.cancel()  # 重复取消也不能释放仍在写入的队列锁。
        await asyncio.sleep(0)
        assert not first.done() and not second.done()
    finally:
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await first
        if second is not None:
            await second
    assert [item.data["request_id"] for item in await queue.list_jobs()] == [
        "first",
        "second",
    ]
