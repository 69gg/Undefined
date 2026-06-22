from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from Undefined.attachments import forward_snapshot
from Undefined.attachments.forward_snapshot import (
    load_forward_snapshot,
    normalize_forward_nodes_for_snapshot,
    save_forward_snapshot,
)


class _OddValue:
    def __str__(self) -> str:
        return "odd-value"


@pytest.mark.asyncio
async def test_forward_snapshot_round_trip(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        forward_snapshot,
        "FORWARD_SNAPSHOT_CACHE_DIR",
        tmp_path / "forward_snapshots",
    )

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
    monkeypatch.setattr(
        forward_snapshot,
        "FORWARD_SNAPSHOT_CACHE_DIR",
        tmp_path / "forward_snapshots",
    )

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
