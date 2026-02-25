"""文件持久化任务队列：pending → processing → complete/failed。"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from Undefined.utils.io import read_json, write_json

logger = logging.getLogger(__name__)


class JobQueue:
    def __init__(self, base_path: str | Path) -> None:
        base = Path(base_path)
        self._pending_dir = base / "pending"
        self._processing_dir = base / "processing"
        self._failed_dir = base / "failed"
        for d in (self._pending_dir, self._processing_dir, self._failed_dir):
            d.mkdir(parents=True, exist_ok=True)
        # 启动时清理所有遗留的 lock 文件
        stale_lock_count = 0
        for d in (self._pending_dir, self._processing_dir, self._failed_dir):
            for lock_file in d.glob("*.lock"):
                lock_file.unlink(missing_ok=True)
                stale_lock_count += 1
        if stale_lock_count:
            logger.info("[认知队列] 清理遗留 lock 文件: count=%s", stale_lock_count)
        logger.info(
            "[认知队列] 初始化完成: base=%s pending=%s processing=%s failed=%s",
            str(base),
            str(self._pending_dir),
            str(self._processing_dir),
            str(self._failed_dir),
        )

    async def enqueue(self, job: dict[str, Any]) -> str:
        request_id = str(job.get("request_id") or str(uuid4()))
        end_seq = job.get("end_seq", 0)
        job_id = f"{request_id}_{end_seq}_{int(time.time() * 1000)}"
        await write_json(self._pending_dir / f"{job_id}.json", job)
        logger.info(
            "[认知队列] 入队成功: job_id=%s request_id=%s user=%s group=%s sender=%s",
            job_id,
            request_id,
            job.get("user_id", ""),
            job.get("group_id", ""),
            job.get("sender_id", ""),
        )
        return job_id

    async def dequeue(self) -> tuple[str, dict[str, Any]] | None:
        def _pick() -> tuple[str, dict[str, Any]] | None:
            files = sorted(self._pending_dir.glob("*.json"))
            for f in files:
                dst = self._processing_dir / f.name
                try:
                    os.replace(f, dst)
                    import json

                    with open(dst, "r", encoding="utf-8") as fh:
                        data = json.load(fh)
                    # 清理遗留的 lock 文件
                    lock_file = f.with_name(f"{f.name}.lock")
                    lock_file.unlink(missing_ok=True)
                    return f.stem, data
                except (OSError, Exception) as exc:
                    logger.warning(
                        "[认知队列] 出队失败，跳过文件: file=%s err=%s",
                        str(f),
                        exc,
                    )
                    continue
            return None

        result = await asyncio.to_thread(_pick)
        if result:
            job_id, data = result
            logger.info(
                "[认知队列] 出队成功: job_id=%s retry_count=%s has_observations=%s",
                job_id,
                data.get("_retry_count", 0),
                data.get("has_observations", data.get("has_new_info", False)),
            )
        return result

    async def complete(self, job_id: str) -> None:
        p = self._processing_dir / f"{job_id}.json"

        def _remove() -> None:
            p.unlink(missing_ok=True)
            p.with_name(f"{p.name}.lock").unlink(missing_ok=True)

        await asyncio.to_thread(_remove)
        logger.info("[认知队列] 任务完成并移除 processing: job_id=%s", job_id)

    async def fail(self, job_id: str, error: str) -> None:
        src = self._processing_dir / f"{job_id}.json"
        data = await read_json(src) or {}
        data["error"] = error
        await write_json(self._failed_dir / f"{job_id}.json", data)

        def _remove() -> None:
            src.unlink(missing_ok=True)
            src.with_name(f"{src.name}.lock").unlink(missing_ok=True)

        await asyncio.to_thread(_remove)
        logger.warning(
            "[认知队列] 任务写入 failed: job_id=%s error=%s",
            job_id,
            error,
        )

    async def requeue(self, job_id: str, error: str) -> None:
        """将 processing 任务移回 pending，递增 _retry_count（原子操作）。"""
        src = self._processing_dir / f"{job_id}.json"
        dst = self._pending_dir / f"{job_id}.json"
        data = await read_json(src) or {}
        data["_retry_count"] = data.get("_retry_count", 0) + 1
        data["_last_error"] = error
        # 先原子更新 processing 内容，再原子移动到 pending
        await write_json(src, data)
        await asyncio.to_thread(lambda: os.replace(src, dst))
        logger.info(
            "[认知队列] 任务回队: job_id=%s retry_count=%s last_error=%s",
            job_id,
            data.get("_retry_count", 0),
            error,
        )

    async def retry_all(self) -> int:
        """将所有 failed 任务移回 pending 队列，返回重试数量。"""

        def _move_all() -> int:
            import json

            count = 0
            for f in self._failed_dir.glob("*.json"):
                try:
                    data = json.loads(f.read_text("utf-8"))
                    data.pop("error", None)
                    dst = self._pending_dir / f.name
                    dst.write_text(json.dumps(data, ensure_ascii=False), "utf-8")
                    f.unlink()
                    f.with_name(f"{f.name}.lock").unlink(missing_ok=True)
                    count += 1
                except (OSError, Exception) as exc:
                    logger.warning(
                        "[认知队列] failed 任务回队失败: file=%s err=%s",
                        str(f),
                        exc,
                    )
                    continue
            return count

        count = await asyncio.to_thread(_move_all)
        logger.info("[认知队列] failed 批量回队完成: count=%s", count)
        return count

    async def recover_stale(self, timeout_seconds: float) -> int:
        def _recover() -> int:
            now = time.time()
            count = 0
            for f in self._processing_dir.glob("*.json"):
                try:
                    if now - f.stat().st_mtime > timeout_seconds:
                        os.replace(f, self._pending_dir / f.name)
                        f.with_name(f"{f.name}.lock").unlink(missing_ok=True)
                        count += 1
                except OSError as exc:
                    logger.warning(
                        "[认知队列] 恢复陈旧任务失败: file=%s err=%s",
                        str(f),
                        exc,
                    )
                    continue
            return count

        count = await asyncio.to_thread(_recover)
        if count > 0:
            logger.info(
                "[认知队列] 已恢复陈旧任务: count=%s timeout_seconds=%s",
                count,
                timeout_seconds,
            )
        else:
            logger.info(
                "[认知队列] 无需恢复陈旧任务: timeout_seconds=%s",
                timeout_seconds,
            )
        return count
