from __future__ import annotations

import asyncio

import pytest

from Undefined.utils.history import MessageHistoryManager


@pytest.mark.asyncio
async def test_add_group_message_with_level_stores_level_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """测试添加带 level 的群消息会正确存储 level 字段"""
    manager = MessageHistoryManager.__new__(MessageHistoryManager)
    manager._message_history = {}
    manager._max_records = 10000
    manager._initialized = asyncio.Event()
    manager._initialized.set()
    manager._group_locks = {}

    saved_data: dict[str, list[dict[str, object]]] = {}

    async def fake_save(data: list[dict[str, object]], path: str) -> None:
        saved_data[path] = data

    monkeypatch.setattr(manager, "_save_history_to_file", fake_save)

    await manager.add_group_message(
        group_id=20001,
        sender_id=10001,
        text_content="测试消息",
        sender_card="测试用户",
        group_name="测试群",
        role="member",
        title="",
        level="Lv.5",
        message_id=123456,
    )

    assert "20001" in manager._message_history
    assert len(manager._message_history["20001"]) == 1

    record = manager._message_history["20001"][0]
    assert record["level"] == "Lv.5"
    assert record["type"] == "group"
    assert record["chat_id"] == "20001"
    assert record["user_id"] == "10001"
    assert record["message"] == "测试消息"
    assert record["role"] == "member"
    assert record["title"] == ""
    assert record["message_id"] == 123456


@pytest.mark.asyncio
async def test_add_group_message_without_level_stores_empty_level(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """测试添加群消息不传 level 参数时默认存储空字符串"""
    manager = MessageHistoryManager.__new__(MessageHistoryManager)
    manager._message_history = {}
    manager._max_records = 10000
    manager._initialized = asyncio.Event()
    manager._initialized.set()
    manager._group_locks = {}

    saved_data: dict[str, list[dict[str, object]]] = {}

    async def fake_save(data: list[dict[str, object]], path: str) -> None:
        saved_data[path] = data

    monkeypatch.setattr(manager, "_save_history_to_file", fake_save)

    await manager.add_group_message(
        group_id=20001,
        sender_id=10001,
        text_content="测试消息",
        sender_card="测试用户",
        group_name="测试群",
    )

    assert "20001" in manager._message_history
    record = manager._message_history["20001"][0]
    assert record["level"] == ""


@pytest.mark.asyncio
async def test_get_recent_returns_messages_with_level_intact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """测试 get_recent 能正确返回带 level 的消息"""
    manager = MessageHistoryManager.__new__(MessageHistoryManager)
    manager._message_history = {
        "20001": [
            {
                "type": "group",
                "chat_id": "20001",
                "chat_name": "测试群",
                "user_id": "10001",
                "display_name": "测试用户",
                "role": "admin",
                "title": "管理员",
                "level": "Lv.10",
                "timestamp": "2026-04-11 10:00:00",
                "message": "第一条消息",
            },
            {
                "type": "group",
                "chat_id": "20001",
                "chat_name": "测试群",
                "user_id": "10002",
                "display_name": "普通用户",
                "role": "member",
                "title": "",
                "level": "Lv.2",
                "timestamp": "2026-04-11 10:01:00",
                "message": "第二条消息",
            },
            {
                "type": "group",
                "chat_id": "20001",
                "chat_name": "测试群",
                "user_id": "10003",
                "display_name": "新用户",
                "role": "member",
                "title": "",
                "level": "",
                "timestamp": "2026-04-11 10:02:00",
                "message": "第三条消息",
            },
        ]
    }
    manager._max_records = 10000
    _evt = asyncio.Event()
    _evt.set()
    manager._initialized = _evt

    messages = manager.get_recent("20001", "group", 0, 10)

    assert len(messages) == 3
    assert messages[0]["level"] == "Lv.10"
    assert messages[1]["level"] == "Lv.2"
    assert messages[2]["level"] == ""


@pytest.mark.asyncio
async def test_add_group_message_with_empty_level_string(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """测试添加群消息显式传入空字符串 level"""
    manager = MessageHistoryManager.__new__(MessageHistoryManager)
    manager._message_history = {}
    manager._max_records = 10000
    manager._initialized = asyncio.Event()
    manager._initialized.set()
    manager._group_locks = {}

    saved_data: dict[str, list[dict[str, object]]] = {}

    async def fake_save(data: list[dict[str, object]], path: str) -> None:
        saved_data[path] = data

    monkeypatch.setattr(manager, "_save_history_to_file", fake_save)

    await manager.add_group_message(
        group_id=20001,
        sender_id=10001,
        text_content="测试消息",
        level="",
    )

    record = manager._message_history["20001"][0]
    assert "level" in record
    assert record["level"] == ""
