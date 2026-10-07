"""Memory mutations publish only ordered, durable commits."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from Undefined.api.routes.memory import (
    memory_create_handler,
    memory_delete_handler,
    memory_update_handler,
)
from Undefined.memory import MemoryStorage
from Undefined.skills.toolsets.memory.add.handler import execute as add_memory_tool
from Undefined.utils import io


@pytest.fixture
def memory_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "memory.json"
    monkeypatch.setattr("Undefined.memory.MEMORY_FILE_PATH", path)
    return path


def _facts(storage: MemoryStorage) -> list[str]:
    return [memory.fact for memory in storage.get_all()]


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_when", ["none", "writing", "waiting"])
async def test_concurrent_memory_commits_remain_ordered_across_cancellation(
    memory_path: Path, monkeypatch: pytest.MonkeyPatch, cancel_when: str
) -> None:
    storage = MemoryStorage()
    started = asyncio.Event()
    release = asyncio.Event()
    writes: list[list[dict[str, str]]] = []
    real_write = io.write_json

    async def gated_write(path: Path | str, data: Any, use_lock: bool = True) -> None:
        writes.append(data)
        if len(writes) == 1:
            started.set()
            await release.wait()
        await real_write(path, data, use_lock)

    monkeypatch.setattr(io, "write_json", gated_write)
    first = asyncio.create_task(storage.add("first"))
    second: asyncio.Task[str | None] | None = None
    try:
        await asyncio.wait_for(started.wait(), 1)
        assert _facts(storage) == []
        if cancel_when == "writing":
            first.cancel()
            await asyncio.sleep(0)
            first.cancel()
        second = asyncio.create_task(storage.add("second"))
        await asyncio.sleep(0)
        assert len(writes) == 1
        assert not first.done()
        if cancel_when == "waiting":
            second.cancel()
        release.set()
        results = await asyncio.gather(first, second, return_exceptions=True)
        assert isinstance(results[0], asyncio.CancelledError) == (
            cancel_when == "writing"
        )
        assert isinstance(results[1], asyncio.CancelledError) == (
            cancel_when == "waiting"
        )
        expected = ["first"] if cancel_when == "waiting" else ["first", "second"]
        assert _facts(storage) == _facts(MemoryStorage()) == expected
        assert [
            item["fact"] for item in json.loads(memory_path.read_text("utf-8"))
        ] == expected
    finally:
        release.set()
        await asyncio.gather(
            first, *([second] if second is not None else []), return_exceptions=True
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["add", "update", "delete", "clear"])
async def test_failed_memory_mutation_preserves_committed_state(
    memory_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    storage = MemoryStorage(max_memories=1)
    memory_uuid = await storage.add("original")
    assert memory_uuid is not None
    before = memory_path.read_bytes()
    failed_write = AsyncMock(side_effect=OSError("isolated ENOSPC"))
    monkeypatch.setattr(io, "write_json", failed_write)
    with pytest.raises(OSError, match="ENOSPC"):
        if operation == "add":
            await storage.add("new")
        elif operation == "update":
            await storage.update(memory_uuid, "new")
        elif operation == "delete":
            await storage.delete(memory_uuid)
        else:
            await storage.clear()
    assert _facts(storage) == ["original"]
    assert _facts(MemoryStorage()) == ["original"]
    assert memory_path.read_bytes() == before


@pytest.mark.asyncio
async def test_memory_failure_is_not_deduplicated_on_healthy_retry(
    memory_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage = MemoryStorage()
    real_write = io.write_json
    monkeypatch.setattr(
        io, "write_json", AsyncMock(side_effect=OSError("isolated ENOSPC"))
    )
    with pytest.raises(OSError):
        await add_memory_tool({"fact": "retry"}, {"memory_storage": storage})
    assert not memory_path.exists()
    assert storage.count() == 0
    monkeypatch.setattr(io, "write_json", real_write)
    result = await add_memory_tool({"fact": "retry"}, {"memory_storage": storage})
    assert result.startswith("已保存记忆:")
    assert _facts(MemoryStorage()) == ["retry"]


@pytest.mark.asyncio
async def test_memory_duplicate_waits_for_initial_commit(
    memory_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage = MemoryStorage()
    started = asyncio.Event()
    release = asyncio.Event()
    real_write = io.write_json

    async def gated_write(path: Path | str, data: Any, use_lock: bool = True) -> None:
        started.set()
        await release.wait()
        await real_write(path, data, use_lock)

    monkeypatch.setattr(io, "write_json", gated_write)
    first = asyncio.create_task(storage.add("same"))
    second: asyncio.Task[str | None] | None = None
    try:
        await asyncio.wait_for(started.wait(), 1)
        second = asyncio.create_task(storage.add("same"))
        await asyncio.sleep(0)
        assert not second.done()
        assert not memory_path.exists()
        release.set()
        first_uuid, second_uuid = await asyncio.gather(first, second)
        assert first_uuid == second_uuid
        assert _facts(MemoryStorage()) == ["same"]
    finally:
        release.set()
        await asyncio.gather(
            first, *([second] if second is not None else []), return_exceptions=True
        )


@pytest.mark.asyncio
async def test_memory_legacy_dedup_persists_generated_uuid(memory_path: Path) -> None:
    memory_path.write_text(
        json.dumps([{"fact": "legacy", "created_at": "2026-01-01 00:00:00"}]), "utf-8"
    )
    storage = MemoryStorage()
    generated_uuid = await storage.add("legacy")
    assert MemoryStorage().get_all()[0].uuid == generated_uuid


def test_get_all_cannot_mutate_committed_memory(
    memory_path: Path,
) -> None:
    memory_path.write_text(
        json.dumps(
            [{"uuid": "u1", "fact": "original", "created_at": "2026-01-01 00:00:00"}]
        ),
        "utf-8",
    )
    storage = MemoryStorage()
    storage.get_all()[0].fact = "uncommitted"
    assert _facts(storage) == ["original"]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["create", "update", "delete"])
async def test_memory_http_returns_failure_without_publishing_uncommitted_state(
    memory_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    storage = MemoryStorage()
    memory_uuid = await storage.add("original")
    context: Any = SimpleNamespace(ai=SimpleNamespace(memory_storage=storage))

    async def create(request: web.Request) -> web.Response:
        return await memory_create_handler(context, request)

    async def update(request: web.Request) -> web.Response:
        return await memory_update_handler(context, request)

    async def delete(request: web.Request) -> web.Response:
        return await memory_delete_handler(context, request)

    app = web.Application()
    app.router.add_post("/memory", create)
    app.router.add_patch("/memory/{uuid}", update)
    app.router.add_delete("/memory/{uuid}", delete)
    real_write = io.write_json
    monkeypatch.setattr(
        io, "write_json", AsyncMock(side_effect=OSError("isolated ENOSPC"))
    )
    async with TestClient(TestServer(app)) as client:
        if operation == "create":
            response = await client.post("/memory", json={"fact": "new"})
        elif operation == "update":
            response = await client.patch(
                f"/memory/{memory_uuid}", json={"fact": "new"}
            )
        else:
            response = await client.delete(f"/memory/{memory_uuid}")
        assert response.status == 500
        assert await response.json() == {"error": "Failed to persist memory"}
        assert _facts(storage) == _facts(MemoryStorage()) == ["original"]
        monkeypatch.setattr(io, "write_json", real_write)
        if operation == "create":
            retry = await client.post("/memory", json={"fact": "new"})
            assert retry.status == 201
            assert _facts(MemoryStorage()) == ["original", "new"]
