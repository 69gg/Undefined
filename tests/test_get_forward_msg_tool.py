from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

import pytest

from Undefined.attachments import forward_snapshot
from Undefined.attachments import AttachmentRegistry
from Undefined.skills.toolsets.messages.get_forward_msg.handler import execute

_PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR"
    b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00"
    b"\x90wS\xde"
    b"\x00\x00\x00\x0cIDATx\x9cc``\x00\x00\x00\x02\x00\x01"
    b"\x0b\xe7\x02\x9d"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)


@pytest.mark.asyncio
async def test_get_forward_msg_accepts_forward_uid_and_registers_nested_refs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        forward_snapshot,
        "FORWARD_SNAPSHOT_CACHE_DIR",
        tmp_path / "forward_snapshots",
    )
    registry = AttachmentRegistry(
        registry_path=tmp_path / "attachment_registry.json",
        cache_dir=tmp_path / "attachments",
    )
    forward_record = await registry.register_forward_reference(
        "group:10001",
        "raw-forward-1",
    )
    payload = base64.b64encode(_PNG_BYTES).decode("ascii")
    seen_ids: list[str] = []

    async def _get_forward(forward_id: str) -> list[dict[str, Any]]:
        seen_ids.append(forward_id)
        return [
            {
                "sender": {"nickname": "Alice", "user_id": 123},
                "time": 1_700_000_000,
                "message": [
                    {"type": "text", "data": {"text": "第一层"}},
                    {"type": "image", "data": {"file": f"base64://{payload}"}},
                    {"type": "forward", "data": {"id": "raw-forward-2"}},
                ],
            }
        ]

    result = await execute(
        {"message_id": forward_record.uid},
        {
            "attachment_registry": registry,
            "get_forward_msg_callback": _get_forward,
            "group_id": 10001,
            "request_type": "group",
        },
    )

    assert seen_ids == ["raw-forward-1", "raw-forward-2"]
    assert "节点 1-1/1" in result
    assert "第一层" in result
    assert '<attachment uid="pic_' in result
    assert '<forward uid="forward_' in result


@pytest.mark.asyncio
async def test_get_forward_msg_supports_raw_id_and_pagination() -> None:
    async def _get_forward(forward_id: str) -> list[dict[str, Any]]:
        assert forward_id == "raw-forward"
        return [
            {"message": [{"type": "text", "data": {"text": "n0"}}]},
            {"message": [{"type": "text", "data": {"text": "n1"}}]},
            {"message": [{"type": "text", "data": {"text": "n2"}}]},
        ]

    result = await execute(
        {"message_id": "raw-forward", "offset": 1, "limit": 1},
        {"get_forward_msg_callback": _get_forward},
    )

    assert "节点 2-2/3" in result
    assert "n1" in result
    assert "n0" not in result
    assert "offset=2" in result


@pytest.mark.asyncio
async def test_get_forward_msg_uses_snapshot_when_nested_forward_becomes_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        forward_snapshot,
        "FORWARD_SNAPSHOT_CACHE_DIR",
        tmp_path / "forward_snapshots",
    )
    registry = AttachmentRegistry(
        registry_path=tmp_path / "attachment_registry.json",
        cache_dir=tmp_path / "attachments",
    )
    outer_record = await registry.register_forward_reference(
        "group:10001",
        "outer-forward",
    )
    seen_ids: list[str] = []

    async def _get_forward(forward_id: str) -> list[dict[str, Any]]:
        seen_ids.append(forward_id)
        if forward_id == "outer-forward":
            return [
                {
                    "sender": {"nickname": "Alice", "user_id": 123},
                    "message": [
                        {"type": "text", "data": {"text": "外层"}},
                        {"type": "forward", "data": {"id": "nested-forward"}},
                    ],
                }
            ]
        if forward_id == "nested-forward" and seen_ids.count("nested-forward") == 1:
            return [
                {
                    "sender": {"nickname": "Bob", "user_id": 456},
                    "message": [
                        {"type": "text", "data": {"text": "内层内容"}},
                    ],
                }
            ]
        return []

    context = {
        "attachment_registry": registry,
        "get_forward_msg_callback": _get_forward,
        "group_id": 10001,
        "request_type": "group",
    }

    outer_result = await execute({"message_id": outer_record.uid}, context)

    assert "外层" in outer_result
    assert "nested-forward" in seen_ids
    nested_records = [
        record
        for record in registry._records.values()
        if record.media_type == "forward" and record.source_ref == "nested-forward"
    ]
    assert len(nested_records) == 1

    nested_result = await execute({"message_id": nested_records[0].uid}, context)

    assert "来自本地快照" in nested_result
    assert "内层内容" in nested_result
    assert seen_ids.count("nested-forward") == 1

    raw_nested_result = await execute({"message_id": "nested-forward"}, context)

    assert "来自本地快照" in raw_nested_result
    assert "内层内容" in raw_nested_result
    assert seen_ids.count("nested-forward") == 1


@pytest.mark.asyncio
async def test_get_forward_msg_reports_unavailable_forward_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        forward_snapshot,
        "FORWARD_SNAPSHOT_CACHE_DIR",
        tmp_path / "forward_snapshots",
    )
    registry = AttachmentRegistry(
        registry_path=tmp_path / "attachment_registry.json",
        cache_dir=tmp_path / "attachments",
    )
    record = await registry.register_forward_reference(
        "group:10001",
        "nested-forward",
        segment_data={"id": "nested-forward", "resid": "resid-forward"},
    )

    async def _get_forward(_forward_id: str) -> list[dict[str, Any]]:
        return []

    result = await execute(
        {"message_id": record.uid},
        {
            "attachment_registry": registry,
            "get_forward_msg_callback": _get_forward,
            "group_id": 10001,
            "request_type": "group",
        },
    )

    assert "协议端当前无法回源该层合并转发" in result
    assert "源 ID: nested-forward" in result
    assert "原始字段:" in result
    assert "resid=resid-forward" in result
