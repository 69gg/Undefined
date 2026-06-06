"""ChromaDB operation scheduler for cognitive vector stores."""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, TypeVar

from Undefined.context import RequestContext

logger = logging.getLogger(__name__)

T = TypeVar("T")

CHROMA_PRIORITY_FOREGROUND_CRITICAL = "foreground_critical"
CHROMA_PRIORITY_FOREGROUND = "foreground"
CHROMA_PRIORITY_MAINTENANCE = "maintenance"
CHROMA_PRIORITY_BACKGROUND = "background"

CHROMA_PRIORITY_DISPLAY_NAMES = {
    CHROMA_PRIORITY_FOREGROUND_CRITICAL: "前台关键",
    CHROMA_PRIORITY_FOREGROUND: "前台",
    CHROMA_PRIORITY_MAINTENANCE: "维护",
    CHROMA_PRIORITY_BACKGROUND: "后台",
}

_PRIORITY_ORDER = (
    CHROMA_PRIORITY_FOREGROUND_CRITICAL,
    CHROMA_PRIORITY_FOREGROUND,
    CHROMA_PRIORITY_MAINTENANCE,
    CHROMA_PRIORITY_BACKGROUND,
)
_FOREGROUND_PRIORITIES = (
    CHROMA_PRIORITY_FOREGROUND_CRITICAL,
    CHROMA_PRIORITY_FOREGROUND,
)
_BACKGROUND_PRIORITIES = (
    CHROMA_PRIORITY_MAINTENANCE,
    CHROMA_PRIORITY_BACKGROUND,
)


def normalize_chroma_priority(value: str | None, default: str) -> str:
    """Normalize external priority values to a known scheduler lane."""
    raw = str(value or "").strip()
    if raw in CHROMA_PRIORITY_DISPLAY_NAMES:
        return raw
    return default


@dataclass
class ChromaOperationReceipt:
    """Execution timing for one Chroma operation."""

    priority: str
    operation: str
    collection: str
    request_id: str
    queue_wait_seconds: float
    exec_seconds: float
    pending_before: int


@dataclass
class _ChromaOperation:
    priority: str
    operation: str
    collection: str
    request_id: str
    callback: Callable[[], Any]
    created_at: float
    pending_before: int
    future: asyncio.Future[tuple[Any, ChromaOperationReceipt]]


@dataclass
class ChromaSchedulerSnapshot:
    running: bool
    stopped: bool
    foreground_burst: int
    active: bool
    pending: dict[str, int] = field(default_factory=dict)


class ChromaOperationScheduler:
    """Single-worker priority scheduler for Chroma collection operations."""

    def __init__(self, *, foreground_burst: int = 8) -> None:
        self._foreground_burst = max(1, int(foreground_burst))
        self._queues: dict[str, deque[_ChromaOperation]] = {
            priority: deque() for priority in _PRIORITY_ORDER
        }
        self._condition = asyncio.Condition()
        self._worker: asyncio.Task[None] | None = None
        self._stopped = False
        self._foreground_since_background = 0
        self._active_operation: _ChromaOperation | None = None

    @property
    def foreground_burst(self) -> int:
        return self._foreground_burst

    def snapshot(self) -> ChromaSchedulerSnapshot:
        return ChromaSchedulerSnapshot(
            running=self._worker is not None and not self._worker.done(),
            stopped=self._stopped,
            foreground_burst=self._foreground_burst,
            active=self._active_operation is not None,
            pending={priority: len(queue) for priority, queue in self._queues.items()},
        )

    async def run(
        self,
        *,
        priority: str,
        operation: str,
        collection: str,
        callback: Callable[[], T],
    ) -> tuple[T, ChromaOperationReceipt]:
        normalized_priority = normalize_chroma_priority(
            priority,
            CHROMA_PRIORITY_FOREGROUND,
        )
        loop = asyncio.get_running_loop()
        future: asyncio.Future[tuple[Any, ChromaOperationReceipt]] = (
            loop.create_future()
        )
        request_id = self._current_request_id()
        created_at = time.perf_counter()
        async with self._condition:
            if self._stopped:
                raise RuntimeError("Chroma operation scheduler has stopped")
            self._ensure_worker_locked()
            pending_before = self._pending_count_locked()
            job = _ChromaOperation(
                priority=normalized_priority,
                operation=operation,
                collection=collection,
                request_id=request_id,
                callback=callback,
                created_at=created_at,
                pending_before=pending_before,
                future=future,
            )
            self._queues[normalized_priority].append(job)
            self._condition.notify()

        try:
            result, receipt = await future
        except asyncio.CancelledError:
            if not future.done():
                future.cancel()
            raise
        return result, receipt

    async def stop(self) -> None:
        worker: asyncio.Task[None] | None
        async with self._condition:
            self._stopped = True
            self._cancel_pending_locked()
            self._condition.notify_all()
            worker = self._worker
        if worker is not None:
            await worker
        self._worker = None

    def _ensure_worker_locked(self) -> None:
        if self._worker is None or self._worker.done():
            self._worker = asyncio.create_task(self._worker_loop())

    async def _worker_loop(self) -> None:
        while True:
            async with self._condition:
                while True:
                    if self._stopped and self._pending_count_locked() == 0:
                        return
                    job = self._pop_next_locked()
                    if job is not None:
                        self._active_operation = job
                        break
                    await self._condition.wait()

            try:
                await self._execute(job)
            finally:
                async with self._condition:
                    self._active_operation = None
                    self._condition.notify_all()

    async def _execute(self, job: _ChromaOperation) -> None:
        if job.future.cancelled():
            return
        wait_seconds = time.perf_counter() - job.created_at
        exec_started = time.perf_counter()
        logger.info(
            "[认知向量库] Chroma 操作开始: priority=%s operation=%s collection=%s request_id=%s wait=%.3fs pending_before=%s",
            job.priority,
            job.operation,
            job.collection,
            job.request_id,
            wait_seconds,
            job.pending_before,
        )
        try:
            result = await asyncio.to_thread(job.callback)
        except Exception as exc:
            exec_seconds = time.perf_counter() - exec_started
            if not job.future.done():
                job.future.set_exception(exc)
            logger.warning(
                "[认知向量库] Chroma 操作失败: priority=%s operation=%s collection=%s request_id=%s wait=%.3fs exec=%.3fs err=%s",
                job.priority,
                job.operation,
                job.collection,
                job.request_id,
                wait_seconds,
                exec_seconds,
                exc,
            )
            return

        exec_seconds = time.perf_counter() - exec_started
        receipt = ChromaOperationReceipt(
            priority=job.priority,
            operation=job.operation,
            collection=job.collection,
            request_id=job.request_id,
            queue_wait_seconds=wait_seconds,
            exec_seconds=exec_seconds,
            pending_before=job.pending_before,
        )
        if not job.future.done():
            job.future.set_result((result, receipt))
        logger.info(
            "[认知向量库] Chroma 操作完成: priority=%s operation=%s collection=%s request_id=%s wait=%.3fs exec=%.3fs",
            job.priority,
            job.operation,
            job.collection,
            job.request_id,
            wait_seconds,
            exec_seconds,
        )

    def _pop_next_locked(self) -> _ChromaOperation | None:
        if (
            self._foreground_since_background >= self._foreground_burst
            and self._has_pending_locked(_BACKGROUND_PRIORITIES)
        ):
            job = self._pop_first_locked(_BACKGROUND_PRIORITIES)
            if job is not None:
                self._foreground_since_background = 0
                return job

        job = self._pop_first_locked(_FOREGROUND_PRIORITIES)
        if job is not None:
            self._foreground_since_background += 1
            return job

        job = self._pop_first_locked(_BACKGROUND_PRIORITIES)
        if job is not None:
            self._foreground_since_background = 0
            return job
        return None

    def _pop_first_locked(self, priorities: tuple[str, ...]) -> _ChromaOperation | None:
        for priority in priorities:
            queue = self._queues[priority]
            while queue:
                job = queue.popleft()
                if not job.future.cancelled():
                    return job
        return None

    def _has_pending_locked(self, priorities: tuple[str, ...]) -> bool:
        return any(self._queues[priority] for priority in priorities)

    def _pending_count_locked(self) -> int:
        return sum(len(queue) for queue in self._queues.values())

    def _cancel_pending_locked(self) -> None:
        for queue in self._queues.values():
            while queue:
                job = queue.popleft()
                if not job.future.done():
                    job.future.cancel()

    @staticmethod
    def _current_request_id() -> str:
        ctx = RequestContext.current()
        if ctx is None:
            return ""
        return str(getattr(ctx, "request_id", "") or "")
