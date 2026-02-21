from __future__ import annotations

import pytest

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
