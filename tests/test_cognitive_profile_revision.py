from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from Undefined.cognitive.historian import HistorianWorker
from Undefined.cognitive.profile_storage import ProfileStorage


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


@pytest.mark.asyncio
async def test_restore_revision_roundtrip_keeps_current_as_snapshot(
    tmp_path: Path,
) -> None:
    storage = ProfileStorage(tmp_path, revision_keep=5)
    await storage.write_profile("user", "10001", "v1")
    await storage.write_profile("user", "10001", "v2")

    revisions = await storage.list_revisions("user", "10001")
    assert len(revisions) == 1
    assert await storage.read_revision("user", "10001", revisions[0]) == "v1"

    restored = await storage.restore_revision("user", "10001", revisions[0])
    assert restored == revisions[0]
    assert await storage.read_profile("user", "10001") == "v1"
    # 恢复前的 v2 被存成了新快照，恢复本身可再次回退
    after = await storage.list_revisions("user", "10001")
    assert len(after) == 2
    contents = [await storage.read_revision("user", "10001", name) for name in after]
    assert "v2" in contents


@pytest.mark.asyncio
async def test_read_revision_missing_returns_none(tmp_path: Path) -> None:
    storage = ProfileStorage(tmp_path)
    assert (
        await storage.read_revision("user", "10001", "20260101000000000000.md") is None
    )


@pytest.mark.asyncio
async def test_read_revision_rejects_path_traversal(tmp_path: Path) -> None:
    storage = ProfileStorage(tmp_path)
    for bad in ("../secret.md", "/etc/passwd", "sub/dir.md", "plain"):
        with pytest.raises(ValueError):
            await storage.read_revision("user", "10001", bad)
    with pytest.raises(ValueError):
        await storage.restore_revision("user", "10001", "../secret.md")


@pytest.mark.asyncio
async def test_restore_revision_missing_raises(tmp_path: Path) -> None:
    storage = ProfileStorage(tmp_path)
    with pytest.raises(FileNotFoundError):
        await storage.restore_revision("user", "10001", "20260101000000000000.md")


@pytest.mark.asyncio
async def test_merge_guard_serializes_read_llm_write_cycles(tmp_path: Path) -> None:
    storage = ProfileStorage(tmp_path)
    order: list[str] = []

    async def merge(tag: str) -> None:
        async with storage.merge_guard("user", "10001"):
            order.append(f"{tag}:enter")
            content = await storage.read_profile("user", "10001")
            await asyncio.sleep(0.05)  # 模拟 LLM 改写耗时
            await storage.write_profile(
                "user", "10001", f"{content or ''}+{tag}".strip("+")
            )
            order.append(f"{tag}:exit")

    await asyncio.gather(merge("a"), merge("b"))

    assert order in (
        ["a:enter", "a:exit", "b:enter", "b:exit"],
        ["b:enter", "b:exit", "a:enter", "a:exit"],
    )
    # 后一个合并看到前一个的写入结果，不再互相覆盖
    assert await storage.read_profile("user", "10001") in {"a+b", "b+a"}


@pytest.mark.asyncio
async def test_merge_profiles_holds_entity_merge_guard() -> None:
    events: list[str] = []

    class _Guard:
        def __init__(self, entity_type: str, entity_id: str) -> None:
            self._key = f"{entity_type}:{entity_id}"

        async def __aenter__(self) -> None:
            events.append(f"enter:{self._key}")

        async def __aexit__(self, *exc: Any) -> bool:
            events.append(f"exit:{self._key}")
            return False

    class _Storage:
        def merge_guard(self, entity_type: str, entity_id: str) -> _Guard:
            return _Guard(entity_type, entity_id)

    worker = HistorianWorker(
        job_queue=None,
        vector_store=None,
        profile_storage=_Storage(),
        ai_client=None,
        config_getter=lambda: SimpleNamespace(),
    )

    async def _fake_merge_target(**kwargs: Any) -> bool:
        events.append("merge")
        return True

    worker._merge_profile_target = _fake_merge_target  # type: ignore[method-assign]

    job: dict[str, Any] = {
        "observations": ["某人在群里说了某事"],
        "profile_targets": [
            {"entity_type": "user", "entity_id": "10001"},
        ],
    }
    await worker._merge_profiles(job, "canonical", "job-1")

    assert events == ["enter:user:10001", "merge", "exit:user:10001"]


@pytest.mark.asyncio
async def test_merge_profiles_without_storage_guard_still_runs() -> None:
    worker = HistorianWorker(
        job_queue=None,
        vector_store=None,
        profile_storage=SimpleNamespace(),
        ai_client=None,
        config_getter=lambda: SimpleNamespace(),
    )

    async def _fake_merge_target(**kwargs: Any) -> bool:
        return True

    worker._merge_profile_target = _fake_merge_target  # type: ignore[method-assign]
    job: dict[str, Any] = {
        "observations": ["x"],
        "profile_targets": [{"entity_type": "user", "entity_id": "10001"}],
    }
    await worker._merge_profiles(job, "canonical", "job-1")


@pytest.mark.asyncio
async def test_poll_loop_respects_max_concurrency() -> None:
    pending: list[dict[str, Any]] = [{"observations": []} for _ in range(6)]
    concurrent = 0
    peak = 0
    processed: list[str] = []

    class _Queue:
        async def dequeue(self) -> tuple[str, dict[str, Any]] | None:
            if not pending:
                return None
            index = len(pending)
            pending.pop()
            return f"job-{index}", {"observations": []}

    config = SimpleNamespace(
        poll_interval_seconds=0.01,
        failed_cleanup_interval=0,
        failed_max_age_days=30,
        failed_max_files=500,
        job_max_retries=0,
    )
    worker = HistorianWorker(
        job_queue=_Queue(),
        vector_store=None,
        profile_storage=None,
        ai_client=None,
        config_getter=lambda: config,
        max_concurrency=2,
    )

    async def _fake_process(job_id: str, job: dict[str, Any]) -> None:
        nonlocal concurrent, peak
        concurrent += 1
        peak = max(peak, concurrent)
        await asyncio.sleep(0.05)
        concurrent -= 1
        processed.append(job_id)

    worker._process_job = _fake_process  # type: ignore[method-assign]

    await worker.start()
    await asyncio.sleep(0.8)
    await worker.stop()

    assert len(processed) == 6
    assert peak <= 2
