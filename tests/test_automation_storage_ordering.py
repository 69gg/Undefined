"""Automation persistence stays ordered across concurrent mutations and cancellation."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from Undefined.automations.service import AutomationService
from Undefined.automations.storage import AutomationStorage
from Undefined.utils import io


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_first", [False, True])
async def test_running_task_save_cannot_restore_concurrently_deleted_task(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cancel_first: bool
) -> None:
    storage = AutomationStorage(tmp_path / "automations.json", tmp_path / "legacy.json")
    service = AutomationService(
        SimpleNamespace(),
        SimpleNamespace(),
        SimpleNamespace(),
        SimpleNamespace(),
        storage,
    )
    service.tasks.update({"a": {"task_id": "a"}, "b": {"task_id": "b"}})
    started = asyncio.Event()
    release = asyncio.Event()
    writes: list[dict[str, Any]] = []
    write_json = io.write_json

    async def gated_write(path: Path | str, data: Any, use_lock: bool = True) -> None:
        writes.append(data)
        if len(writes) == 1:
            started.set()
            await release.wait()
        await write_json(path, data, use_lock=use_lock)

    monkeypatch.setattr(io, "write_json", gated_write)
    first = asyncio.create_task(service._mark_run("a", status="ok"))
    second: asyncio.Task[bool] | None = None
    try:
        await asyncio.wait_for(started.wait(), 1)
        if cancel_first:
            first.cancel()
        second = asyncio.create_task(service.remove_task("b"))
        await asyncio.sleep(0)
        assert "b" not in service.tasks
        assert len(writes) == 1
        release.set()
        results = await asyncio.gather(first, second, return_exceptions=True)
        if cancel_first:
            assert isinstance(results[0], asyncio.CancelledError)
        else:
            assert results[0] is None
        assert results[1] is True
        saved = json.loads(storage.path.read_text("utf-8"))
        assert set(saved) == {"a"}
        assert saved["a"]["current_executions"] == 1
        assert set(storage.load_tasks()) == {"a"}
    finally:
        release.set()
        await asyncio.gather(
            first, *([second] if second is not None else []), return_exceptions=True
        )
        service.shutdown()


@pytest.mark.asyncio
async def test_snapshot_does_not_change_while_disk_write_is_pending(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage = AutomationStorage(tmp_path / "automations.json", tmp_path / "legacy.json")
    tasks: dict[str, Any] = {"a": {"nodes": [{"args": {"message": "before"}}]}}
    started = asyncio.Event()
    release = asyncio.Event()
    write_json = io.write_json

    async def gated_write(path: Path | str, data: Any, use_lock: bool = True) -> None:
        started.set()
        await release.wait()
        await write_json(path, data, use_lock=use_lock)

    monkeypatch.setattr(io, "write_json", gated_write)
    saving = asyncio.create_task(storage.save_all(tasks))
    try:
        await asyncio.wait_for(started.wait(), 1)
        tasks["a"]["nodes"][0]["args"]["message"] = "after"
    finally:
        release.set()
        await saving
    saved = json.loads(storage.path.read_text("utf-8"))
    assert saved["a"]["nodes"][0]["args"]["message"] == "before"
