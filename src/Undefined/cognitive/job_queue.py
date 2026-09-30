"""单进程文件任务队列：持久化入队顺序与原子阶段切换。"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections.abc import Callable, Collection
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, TypeVar
from uuid import uuid4

from Undefined.utils.io import run_cancellation_safe, write_json_sync

logger = logging.getLogger(__name__)
_T = TypeVar("_T")
QueueState = Literal["pending", "processing", "failed"]


def job_order(job_id: str, job: dict[str, Any]) -> tuple[int, str]:
    """旧 ID 末尾为入队毫秒；mtime 会随重试改变，不能用作顺序。"""
    order = job.get("_enqueue_order")
    if isinstance(order, int) and not isinstance(order, bool) and order > 0:
        return order, job_id
    try:
        return int(job_id.rsplit("_", 1)[-1]) * 1_000_000, job_id
    except ValueError:
        pass
    for field in ("timestamp_utc", "timestamp_local"):
        try:
            stamp = datetime.fromisoformat(str(job.get(field, "")))
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
            return int(stamp.timestamp() * 1_000_000_000), job_id
        except (ValueError, OverflowError, OSError):
            continue
    try:
        return int(float(job.get("timestamp_epoch", 0)) * 1_000_000_000), job_id
    except (TypeError, ValueError, OverflowError):
        return 0, job_id


@dataclass(frozen=True)
class QueuedJob:
    job_id: str
    data: dict[str, Any]
    state: QueueState


class JobQueue:
    def __init__(self, base_path: str | Path) -> None:
        base = Path(base_path)
        self._pending_dir = base / "pending"
        self._processing_dir = base / "processing"
        self._failed_dir = base / "failed"
        self._lock = asyncio.Lock()
        self._last_order: int | None = None
        for directory in (self._pending_dir, self._processing_dir, self._failed_dir):
            directory.mkdir(parents=True, exist_ok=True)
            for lock_file in directory.glob("*.lock"):
                lock_file.unlink(missing_ok=True)

    async def _run_locked(self, operation: Callable[[], _T]) -> _T:
        # to_thread 被取消时磁盘操作仍可能执行，必须等其收敛后才释放队列锁。
        async with self._lock:
            return await run_cancellation_safe(asyncio.to_thread(operation))

    @staticmethod
    def _read(path: Path) -> dict[str, Any]:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"任务载荷必须是 JSON object: {path}")
        return data

    def _entries(self, *, include_failed: bool = False) -> list[QueuedJob]:
        directories: list[tuple[QueueState, Path]] = [
            ("pending", self._pending_dir),
            ("processing", self._processing_dir),
        ]
        if include_failed:
            directories.append(("failed", self._failed_dir))
        entries: list[QueuedJob] = []
        for state, directory in directories:
            for path in directory.glob("*.json"):
                try:
                    data = self._read(path)
                except (OSError, ValueError):
                    # failed 清理可与顺序基准恢复并行；终态坏文件不应阻断新任务。
                    # 未完成文件则必须暴露错误，不能忽略可能存在的实体前驱。
                    if state != "failed":
                        raise
                    logger.warning("[认知队列] 跳过不可读的 failed 文件: %s", path)
                    continue
                entries.append(QueuedJob(path.stem, data, state))
        return sorted(entries, key=lambda item: job_order(item.job_id, item.data))

    def _next_order(self) -> int:
        if self._last_order is None:
            last_order = 0
            for directory in (
                self._pending_dir,
                self._processing_dir,
                self._failed_dir,
            ):
                for path in directory.glob("*.json"):
                    try:
                        data = self._read(path)
                    except (OSError, ValueError):
                        # 入队只需恢复顺序基准；调度仍严格读取未完成任务。
                        logger.warning(
                            "[认知队列] 顺序恢复使用不可读任务的 ID: %s", path
                        )
                        data = {}
                    last_order = max(last_order, job_order(path.stem, data)[0])
            self._last_order = last_order
        self._last_order = max(time.time_ns(), self._last_order + 1)
        return self._last_order

    @staticmethod
    def _move(source: Path, destination: Path) -> None:
        os.replace(source, destination)
        source.with_name(f"{source.name}.lock").unlink(missing_ok=True)

    async def enqueue(self, job: dict[str, Any]) -> str:
        def _enqueue() -> str:
            data = dict(job)
            order = self._next_order()
            data["_enqueue_order"] = order
            request_id = str(data.get("request_id") or uuid4())
            job_id = f"{request_id}_{data.get('end_seq', 0)}_{uuid4().hex}_{order // 1_000_000}"
            write_json_sync(self._pending_dir / f"{job_id}.json", data)
            return job_id

        job_id = await self._run_locked(_enqueue)
        logger.info("[认知队列] 入队成功: job_id=%s", job_id)
        return job_id

    async def list_jobs(self) -> list[QueuedJob]:
        """一致读取 pending/processing；遗留 processing 也参与实体顺序。"""
        return await self._run_locked(self._entries)

    def _claim(self, job_id: str) -> tuple[str, dict[str, Any]] | None:
        source = self._pending_dir / f"{job_id}.json"
        if not source.exists():
            return None
        data = self._read(source)
        self._move(source, self._processing_dir / source.name)
        return job_id, data

    async def claim(self, job_id: str) -> tuple[str, dict[str, Any]] | None:
        return await self._run_locked(lambda: self._claim(job_id))

    async def dequeue(self) -> tuple[str, dict[str, Any]] | None:
        """兼容普通消费者；史官通过 list_jobs/claim 选择就绪阶段。"""

        def _pick() -> tuple[str, dict[str, Any]] | None:
            for entry in self._entries():
                if entry.state == "pending":
                    return self._claim(entry.job_id)
            return None

        return await self._run_locked(_pick)

    async def checkpoint(self, job_id: str, job: dict[str, Any]) -> None:
        def _save() -> None:
            path = self._processing_dir / f"{job_id}.json"
            if not path.is_file():
                raise FileNotFoundError(path)
            write_json_sync(path, job)

        await self._run_locked(_save)

    async def release(self, job_id: str) -> None:
        """正常阶段切换：保留顺序、进度和重试次数。"""
        await self._run_locked(
            lambda: self._move(
                self._processing_dir / f"{job_id}.json",
                self._pending_dir / f"{job_id}.json",
            )
        )

    async def complete(self, job_id: str) -> None:
        def _remove() -> None:
            path = self._processing_dir / f"{job_id}.json"
            path.unlink(missing_ok=True)
            path.with_name(f"{path.name}.lock").unlink(missing_ok=True)

        await self._run_locked(_remove)
        logger.info("[认知队列] 任务完成: job_id=%s", job_id)

    async def fail(self, job_id: str, error: str) -> None:
        def _fail() -> None:
            source = self._processing_dir / f"{job_id}.json"
            data = self._read(source)
            data["error"] = error
            write_json_sync(source, data)
            self._move(source, self._failed_dir / source.name)

        await self._run_locked(_fail)
        logger.warning("[认知队列] 任务失败: job_id=%s error=%s", job_id, error)

    async def requeue(self, job_id: str, error: str) -> None:
        def _requeue() -> None:
            source = self._processing_dir / f"{job_id}.json"
            data = self._read(source)
            data["_retry_count"] = int(data.get("_retry_count", 0)) + 1
            data["_last_error"] = error
            write_json_sync(source, data)
            self._move(source, self._pending_dir / source.name)

        await self._run_locked(_requeue)
        logger.info("[认知队列] 自动重试: job_id=%s error=%s", job_id, error)

    async def retry_all(self) -> int:
        """人工重试终态失败任务：保留原事件与完成进度，重新排到队尾。"""

        def _retry() -> int:
            count = 0
            for entry in self._entries(include_failed=True):
                if entry.state != "failed":
                    continue
                data = entry.data
                data.pop("error", None)
                data.pop("_last_error", None)
                data["_retry_count"] = 0
                data["_enqueue_order"] = self._next_order()
                source = self._failed_dir / f"{entry.job_id}.json"
                write_json_sync(source, data)
                self._move(source, self._pending_dir / source.name)
                count += 1
            return count

        return await self._run_locked(_retry)

    async def recover_stale(
        self, timeout_seconds: float, *, exclude_job_ids: Collection[str] = ()
    ) -> int:
        excluded = frozenset(exclude_job_ids)

        def _recover() -> int:
            now = time.time()
            count = 0
            for path in self._processing_dir.glob("*.json"):
                if path.stem in excluded:
                    continue
                if now - path.stat().st_mtime > timeout_seconds:
                    self._move(path, self._pending_dir / path.name)
                    count += 1
            return count

        count = await self._run_locked(_recover)
        if count:
            logger.info("[认知队列] 恢复遗留任务: count=%s", count)
        return count

    def snapshot(self) -> dict[str, Any]:
        return {
            "pending": sum(1 for _ in self._pending_dir.glob("*.json")),
            "processing": sum(1 for _ in self._processing_dir.glob("*.json")),
            "failed": sum(1 for _ in self._failed_dir.glob("*.json")),
            "paths": {
                "pending": str(self._pending_dir),
                "processing": str(self._processing_dir),
                "failed": str(self._failed_dir),
            },
        }
