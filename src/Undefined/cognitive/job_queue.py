"""文件持久化任务队列：pending → processing → complete/failed。"""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from Undefined.utils.io import read_json, write_json


class JobQueue:
    def __init__(self, base_path: str | Path) -> None:
        base = Path(base_path)
        self._pending_dir = base / "pending"
        self._processing_dir = base / "processing"
        self._failed_dir = base / "failed"
        for d in (self._pending_dir, self._processing_dir, self._failed_dir):
            d.mkdir(parents=True, exist_ok=True)

    async def enqueue(self, job: dict[str, Any]) -> str:
        job_id = f"{job.get('request_id', str(uuid4()))}_{job.get('end_seq', 0)}_{int(time.time() * 1000)}"
        await write_json(self._pending_dir / f"{job_id}.json", job)
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
                    return f.stem, data
                except (OSError, Exception):
                    continue
            return None

        return await asyncio.to_thread(_pick)

    async def complete(self, job_id: str) -> None:
        p = self._processing_dir / f"{job_id}.json"
        await asyncio.to_thread(lambda: p.unlink(missing_ok=True))

    async def fail(self, job_id: str, error: str) -> None:
        src = self._processing_dir / f"{job_id}.json"
        data = await read_json(src) or {}
        data["error"] = error
        await write_json(self._failed_dir / f"{job_id}.json", data)
        await asyncio.to_thread(lambda: src.unlink(missing_ok=True))

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
                    count += 1
                except (OSError, Exception):
                    continue
            return count

        return await asyncio.to_thread(_move_all)

    async def recover_stale(self, timeout_seconds: float) -> int:
        def _recover() -> int:
            now = time.time()
            count = 0
            for f in self._processing_dir.glob("*.json"):
                try:
                    if now - f.stat().st_mtime > timeout_seconds:
                        os.replace(f, self._pending_dir / f.name)
                        count += 1
                except OSError:
                    continue
            return count

        return await asyncio.to_thread(_recover)
