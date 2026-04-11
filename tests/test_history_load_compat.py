from __future__ import annotations

from pathlib import Path

import pytest

from Undefined.attachments import AttachmentRecord, AttachmentRegistry
from Undefined.utils.recent_messages import get_recent_messages_prefer_local
from Undefined.utils.history import MessageHistoryManager


@pytest.mark.asyncio
async def test_load_group_history_backfills_chat_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_read_json(
        _path: str, use_lock: bool = False
    ) -> list[dict[str, str]]:
        assert use_lock is False
        return [{"user_id": "20001", "message": "旧消息"}]

    monkeypatch.setattr("Undefined.utils.io.read_json", fake_read_json)
    manager = MessageHistoryManager.__new__(MessageHistoryManager)

    history = await manager._load_history_from_file("data/history/group_30001.json")

    assert len(history) == 1
    record = history[0]
    assert record["type"] == "group"
    assert record["chat_id"] == "30001"
    assert record["chat_name"] == "群30001"
    assert record["user_id"] == "20001"
    assert record["display_name"] == "20001"
    assert record["message"] == "旧消息"


@pytest.mark.asyncio
async def test_load_private_history_backfills_user_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_read_json(
        _path: str, use_lock: bool = False
    ) -> list[dict[str, str]]:
        assert use_lock is False
        return [{"content": "旧私聊"}]

    monkeypatch.setattr("Undefined.utils.io.read_json", fake_read_json)
    manager = MessageHistoryManager.__new__(MessageHistoryManager)

    history = await manager._load_history_from_file("data/history/private_40001.json")

    assert len(history) == 1
    record = history[0]
    assert record["type"] == "private"
    assert record["chat_id"] == "40001"
    assert record["chat_name"] == "QQ用户40001"
    assert record["user_id"] == "40001"
    assert record["display_name"] == "40001"
    assert record["message"] == "旧私聊"


@pytest.mark.asyncio
async def test_load_history_preserves_attachment_semantic_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_read_json(
        _path: str, use_lock: bool = False
    ) -> list[dict[str, object]]:
        assert use_lock is False
        return [
            {
                "user_id": "20001",
                "message": "旧消息",
                "attachments": [
                    {
                        "uid": "pic_old01",
                        "kind": "image",
                        "media_type": "image",
                        "display_name": "meme.png",
                        "source_kind": "meme_library",
                        "semantic_kind": "meme",
                        "description": "无语猫猫表情包",
                    }
                ],
            }
        ]

    monkeypatch.setattr("Undefined.utils.io.read_json", fake_read_json)
    manager = MessageHistoryManager.__new__(MessageHistoryManager)

    history = await manager._load_history_from_file("data/history/group_30001.json")

    assert len(history) == 1
    attachments = history[0]["attachments"]
    assert attachments == [
        {
            "uid": "pic_old01",
            "kind": "image",
            "media_type": "image",
            "display_name": "meme.png",
            "source_kind": "meme_library",
            "semantic_kind": "meme",
            "description": "无语猫猫表情包",
        }
    ]


@pytest.mark.asyncio
async def test_recent_messages_lazily_backfills_meme_attachments(
    tmp_path: Path,
) -> None:
    history_messages: list[dict[str, object]] = [
        {
            "type": "group",
            "chat_id": "30001",
            "chat_name": "群30001",
            "user_id": "10000",
            "display_name": "Bot",
            "timestamp": "2026-04-11 12:00:00",
            "message": "[图片 uid=pic_global01 name=meme.png]",
        }
    ]

    class _DummyHistoryManager:
        def get_recent(
            self, _chat_id: str, _msg_type: str, _start: int, _end: int
        ) -> list[dict[str, object]]:
            return history_messages

    registry = AttachmentRegistry(
        registry_path=tmp_path / "attachment_registry.json",
        cache_dir=tmp_path / "attachments",
    )
    registry.set_global_image_resolver(
        lambda uid: (
            AttachmentRecord(
                uid=uid,
                scope_key="",
                kind="image",
                media_type="image",
                display_name="meme.png",
                source_kind="meme_library",
                source_ref="file:///tmp/meme.png",
                local_path=None,
                mime_type="image/png",
                sha256="deadbeef",
                created_at="2026-04-11T12:00:00",
                segment_data={"subType": "1"},
                semantic_kind="meme",
                description="无语猫猫表情包",
            )
            if uid == "pic_global01"
            else None
        )
    )

    recent_messages = await get_recent_messages_prefer_local(
        chat_id="30001",
        msg_type="group",
        start=0,
        end=10,
        onebot_client=None,
        history_manager=_DummyHistoryManager(),
        bot_qq=10000,
        attachment_registry=registry,
    )

    assert "attachments" not in history_messages[0]
    assert recent_messages[0]["attachments"] == [
        {
            "uid": "pic_global01",
            "kind": "image",
            "media_type": "image",
            "display_name": "meme.png",
            "source_kind": "meme_library",
            "semantic_kind": "meme",
            "description": "无语猫猫表情包",
        }
    ]
