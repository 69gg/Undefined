from __future__ import annotations

import asyncio
import threading
from typing import Any

import pytest

from Undefined.cognitive.chroma_scheduler import (
    CHROMA_PRIORITY_BACKGROUND,
    CHROMA_PRIORITY_FOREGROUND,
    CHROMA_PRIORITY_MAINTENANCE,
    ChromaOperationScheduler,
)


@pytest.mark.asyncio
async def test_chroma_scheduler_runs_one_operation_at_a_time() -> None:
    scheduler = ChromaOperationScheduler()
    active = 0
    max_active = 0

    async def _submit(index: int) -> int:
        def _work() -> int:
            nonlocal active, max_active
            active += 1
            max_active = max(max_active, active)
            try:
                return index
            finally:
                active -= 1

        result, _receipt = await scheduler.run(
            priority=CHROMA_PRIORITY_FOREGROUND,
            operation="query",
            collection="cognitive_events",
            callback=_work,
        )
        return int(result)

    results = await asyncio.gather(*[_submit(index) for index in range(8)])
    await scheduler.stop()

    assert results == list(range(8))
    assert max_active == 1


@pytest.mark.asyncio
async def test_chroma_scheduler_prefers_foreground_over_background() -> None:
    scheduler = ChromaOperationScheduler(foreground_burst=8)
    release_first = threading.Event()
    order: list[str] = []

    def _blocking_first() -> str:
        release_first.wait()
        order.append("first")
        return "first"

    def _record(name: str) -> str:
        order.append(name)
        return name

    async def _submit(name: str, priority: str, callback: Any | None = None) -> str:
        result, _receipt = await scheduler.run(
            priority=priority,
            operation=name,
            collection="cognitive_events",
            callback=callback or (lambda: _record(name)),
        )
        return str(result)

    first_task = asyncio.create_task(
        _submit("first", CHROMA_PRIORITY_BACKGROUND, _blocking_first)
    )
    while scheduler.snapshot().active is False:
        await asyncio.sleep(0)
    background_task = asyncio.create_task(
        _submit("background", CHROMA_PRIORITY_BACKGROUND)
    )
    foreground_task = asyncio.create_task(
        _submit("foreground", CHROMA_PRIORITY_FOREGROUND)
    )
    while sum(scheduler.snapshot().pending.values()) < 2:
        await asyncio.sleep(0)

    release_first.set()

    assert await first_task == "first"
    assert await foreground_task == "foreground"
    assert await background_task == "background"
    await scheduler.stop()

    assert order == ["first", "foreground", "background"]


@pytest.mark.asyncio
async def test_chroma_scheduler_gives_background_a_fairness_slot() -> None:
    scheduler = ChromaOperationScheduler(foreground_burst=2)
    release_first = threading.Event()
    order: list[str] = []

    def _blocking_first() -> str:
        release_first.wait()
        order.append("first")
        return "first"

    def _record(name: str) -> str:
        order.append(name)
        return name

    async def _submit(name: str, priority: str, callback: Any | None = None) -> str:
        result, _receipt = await scheduler.run(
            priority=priority,
            operation=name,
            collection="cognitive_events",
            callback=callback or (lambda: _record(name)),
        )
        return str(result)

    tasks = [
        asyncio.create_task(
            _submit("first", CHROMA_PRIORITY_FOREGROUND, _blocking_first)
        ),
        asyncio.create_task(_submit("fg1", CHROMA_PRIORITY_FOREGROUND)),
        asyncio.create_task(_submit("fg2", CHROMA_PRIORITY_FOREGROUND)),
        asyncio.create_task(_submit("fg3", CHROMA_PRIORITY_FOREGROUND)),
        asyncio.create_task(_submit("maintenance", CHROMA_PRIORITY_MAINTENANCE)),
    ]
    while scheduler.snapshot().active is False:
        await asyncio.sleep(0)
    while sum(scheduler.snapshot().pending.values()) < 4:
        await asyncio.sleep(0)
    release_first.set()

    await asyncio.gather(*tasks)
    await scheduler.stop()

    assert order == ["first", "fg1", "maintenance", "fg2", "fg3"]


@pytest.mark.asyncio
async def test_chroma_scheduler_cancelled_pending_operation_is_skipped() -> None:
    scheduler = ChromaOperationScheduler()
    release_first = threading.Event()
    ran_cancelled = False

    def _blocking_first() -> str:
        release_first.wait()
        return "first"

    def _mark_cancelled() -> str:
        nonlocal ran_cancelled
        ran_cancelled = True
        return "pending"

    first_task = asyncio.create_task(
        scheduler.run(
            priority=CHROMA_PRIORITY_FOREGROUND,
            operation="first",
            collection="cognitive_events",
            callback=_blocking_first,
        )
    )
    while scheduler.snapshot().active is False:
        await asyncio.sleep(0)

    pending_task = asyncio.create_task(
        scheduler.run(
            priority=CHROMA_PRIORITY_BACKGROUND,
            operation="pending",
            collection="cognitive_events",
            callback=lambda: _mark_cancelled(),
        )
    )
    await asyncio.sleep(0)
    pending_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending_task

    release_first.set()
    await first_task
    await scheduler.stop()

    assert ran_cancelled is False


@pytest.mark.asyncio
async def test_chroma_scheduler_propagates_operation_errors() -> None:
    scheduler = ChromaOperationScheduler()

    def _raise() -> str:
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        await scheduler.run(
            priority=CHROMA_PRIORITY_FOREGROUND,
            operation="query",
            collection="cognitive_events",
            callback=_raise,
        )
    await scheduler.stop()
