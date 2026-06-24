from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from Undefined.attachments import forward_snapshot
from Undefined.attachments.forward_snapshot import (
    load_forward_snapshot,
    normalize_forward_nodes_for_snapshot,
    save_forward_snapshot,
    snapshot_forward_tree,
)


class _OddValue:
    def __str__(self) -> str:
        return "odd-value"


def _reset_forward_snapshot_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        forward_snapshot,
        "FORWARD_SNAPSHOT_CACHE_DIR",
        tmp_path / "forward_snapshots",
    )
    monkeypatch.setattr(forward_snapshot, "_snapshot_locks", {})
    monkeypatch.setattr(forward_snapshot, "_snapshot_lock_users", {})
    monkeypatch.setattr(forward_snapshot, "_snapshot_inflight", {})


@pytest.mark.asyncio
async def test_forward_snapshot_round_trip(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reset_forward_snapshot_state(tmp_path, monkeypatch)

    saved = await save_forward_snapshot(
        scope_key="group:10001",
        forward_id="raw-forward",
        nodes=[
            {
                "sender": {"nickname": "Alice", "user_id": 123},
                "message": [{"type": "text", "data": {"text": "hello"}}],
            }
        ],
    )

    assert saved is True
    loaded = await load_forward_snapshot(
        scope_key="group:10001",
        forward_id="raw-forward",
    )
    assert loaded == [
        {
            "sender": {"nickname": "Alice", "user_id": 123},
            "message": [{"type": "text", "data": {"text": "hello"}}],
        }
    ]


@pytest.mark.asyncio
async def test_forward_snapshot_is_scoped(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reset_forward_snapshot_state(tmp_path, monkeypatch)

    await save_forward_snapshot(
        scope_key="group:10001",
        forward_id="raw-forward",
        nodes=[{"message": [{"type": "text", "data": {"text": "group"}}]}],
    )

    assert (
        await load_forward_snapshot(scope_key="group:20002", forward_id="raw-forward")
        == []
    )


def test_normalize_forward_nodes_for_snapshot_cleans_values() -> None:
    nodes: list[dict[str, Any]] = [
        {
            "message": [{"type": "text", "data": {"text": _OddValue()}}],
            "ignored": object(),
        }
    ]

    assert normalize_forward_nodes_for_snapshot(nodes) == [
        {
            "message": [{"type": "text", "data": {"text": "odd-value"}}],
            "ignored": str(nodes[0]["ignored"]),
        }
    ]


@pytest.mark.asyncio
async def test_snapshot_forward_tree_recursively_saves_nested_forwards(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reset_forward_snapshot_state(tmp_path, monkeypatch)
    calls: list[str] = []

    async def _get_forward(forward_id: str) -> list[dict[str, Any]]:
        calls.append(forward_id)
        if forward_id == "outer":
            return [
                {
                    "message": [
                        {"type": "text", "data": {"text": "外层"}},
                        {"type": "forward", "data": {"id": "inner"}},
                    ]
                }
            ]
        if forward_id == "inner":
            return [
                {
                    "message": [
                        {"type": "text", "data": {"text": "内层"}},
                    ]
                }
            ]
        return []

    await snapshot_forward_tree(
        scope_key="group:10001",
        forward_id="outer",
        get_forward_messages=_get_forward,
    )

    assert calls == ["outer", "inner"]
    assert await load_forward_snapshot(
        scope_key="group:10001",
        forward_id="outer",
    ) == [
        {
            "message": [
                {"type": "text", "data": {"text": "外层"}},
                {"type": "forward", "data": {"id": "inner"}},
            ]
        }
    ]
    assert await load_forward_snapshot(
        scope_key="group:10001",
        forward_id="inner",
    ) == [
        {
            "message": [
                {"type": "text", "data": {"text": "内层"}},
            ]
        }
    ]
    assert forward_snapshot._snapshot_locks == {}
    assert forward_snapshot._snapshot_lock_users == {}
    assert forward_snapshot._snapshot_inflight == {}


@pytest.mark.asyncio
async def test_snapshot_forward_tree_coalesces_concurrent_root_fetches(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reset_forward_snapshot_state(tmp_path, monkeypatch)
    calls = 0
    release = asyncio.Event()

    async def _get_forward(forward_id: str) -> list[dict[str, Any]]:
        nonlocal calls
        calls += 1
        assert forward_id == "outer"
        await release.wait()
        return [{"message": [{"type": "text", "data": {"text": "内容"}}]}]

    first = asyncio.create_task(
        snapshot_forward_tree(
            scope_key="group:10001",
            forward_id="outer",
            get_forward_messages=_get_forward,
        )
    )
    await asyncio.sleep(0)
    second = asyncio.create_task(
        snapshot_forward_tree(
            scope_key="group:10001",
            forward_id="outer",
            get_forward_messages=_get_forward,
        )
    )
    await asyncio.sleep(0)
    release.set()

    await asyncio.gather(first, second)

    assert calls == 1
    assert forward_snapshot._snapshot_locks == {}
    assert forward_snapshot._snapshot_lock_users == {}
    assert forward_snapshot._snapshot_inflight == {}
