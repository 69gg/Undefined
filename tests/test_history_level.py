from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from Undefined.utils.history import MessageHistoryManager
from Undefined.utils.message_reply import ReplyContext


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
    await manager.flush_pending_saves()

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
    await manager.flush_pending_saves()

    assert "20001" in manager._message_history
    record = manager._message_history["20001"][0]
    assert record["level"] == ""


@pytest.mark.asyncio
async def test_add_private_message_stores_webchat_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = MessageHistoryManager.__new__(MessageHistoryManager)
    manager._private_message_history = {}
    manager._max_records = 10000
    manager._initialized = asyncio.Event()
    manager._initialized.set()
    manager._private_locks = {}

    saved_data: dict[str, list[dict[str, object]]] = {}

    async def fake_save(data: list[dict[str, object]], path: str) -> None:
        saved_data[path] = data

    monkeypatch.setattr(manager, "_save_history_to_file", fake_save)

    webchat: dict[str, object] = {
        "display_only": True,
        "job_id": "job_1",
        "events": [
            {
                "seq": 2,
                "event": "tool_end",
                "payload": {"tool_call_id": "call_1"},
            }
        ],
    }
    await manager.add_private_message(
        user_id=42,
        text_content="",
        display_name="Bot",
        webchat=webchat,
    )
    await manager.flush_pending_saves()

    record = manager._private_message_history["42"][0]
    assert record["message"] == ""
    assert record["webchat"] == webchat


@pytest.mark.asyncio
async def test_private_history_persists_reply_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = MessageHistoryManager.__new__(MessageHistoryManager)
    manager._private_message_history = {}
    manager._max_records = 10000
    manager._initialized = asyncio.Event()
    manager._initialized.set()
    manager._private_locks = {}

    async def fake_save(_data: object, _path: str) -> None:
        return None

    monkeypatch.setattr(manager, "_save_history_to_file", fake_save)
    reply_context = ReplyContext(
        title="微信用户",
        message_id="quoted-1",
        text="被引用的消息",
    )

    await manager.add_private_message(
        user_id=12345,
        text_content="当前消息",
        message_id="current-1",
        transport={"channel": "wechat", "address": "wechat:12345"},
        reply_context=reply_context,
    )
    await manager.flush_pending_saves()

    record = manager._private_message_history["12345"][0]
    assert record["reply_context"] == reply_context.to_dict()


@pytest.mark.asyncio
async def test_find_private_message_by_id_enforces_transport_route() -> None:
    manager = MessageHistoryManager.__new__(MessageHistoryManager)
    manager._private_message_history = {
        "12345": [
            {
                "message_id": "same-id",
                "message": "QQ 消息",
                "transport": {"channel": "qq", "address": "qq:12345"},
            },
            {
                "message_id": "same-id",
                "message": "另一个微信地址",
                "transport": {
                    "channel": "wechat",
                    "address": "wechat:54321",
                },
            },
            {
                "message_id": "first-client-id",
                "message": "当前微信地址",
                "transport": {
                    "channel": "wechat",
                    "address": "wechat:12345",
                    "message_ids": ["first-client-id", "second-client-id"],
                },
            },
        ]
    }
    manager._initialized = asyncio.Event()
    manager._initialized.set()
    manager._private_locks = {}

    found = await manager.find_private_message_by_id(
        12345,
        "second-client-id",
        channel="wechat",
        address="wechat:12345",
    )
    wrong_route = await manager.find_private_message_by_id(
        12345,
        "same-id",
        channel="wechat",
        address="wechat:12345",
    )

    assert found is not None
    assert found["message"] == "当前微信地址"
    assert wrong_route is None


@pytest.mark.asyncio
async def test_history_save_failure_keeps_pending_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from Undefined.utils import io

    manager = MessageHistoryManager.__new__(MessageHistoryManager)
    manager._max_records = 10000
    manager._pending_history_saves = {}
    manager._history_save_tasks = {}
    path = str(tmp_path / "group_20001.json")
    attempts = 0
    saved_data: list[list[dict[str, object]]] = []

    async def fake_write_json(
        saved_path: str,
        data: list[dict[str, object]],
        *,
        use_lock: bool = True,
    ) -> None:
        nonlocal attempts
        assert saved_path == path
        assert use_lock is True
        attempts += 1
        if attempts == 1:
            raise OSError("disk full")
        saved_data.append(data)

    monkeypatch.setattr(io, "write_json", fake_write_json)

    first_snapshot = [{"message": "first"}]
    manager._queue_history_save(first_snapshot, path)
    await manager.flush_pending_saves()

    assert manager._pending_history_saves[path] == first_snapshot
    assert path not in manager._history_save_tasks

    second_snapshot = [{"message": "second"}]
    manager._queue_history_save(second_snapshot, path)
    await manager.flush_pending_saves()

    assert manager._pending_history_saves == {}
    assert saved_data == [second_snapshot]


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
    await manager.flush_pending_saves()

    record = manager._message_history["20001"][0]
    assert "level" in record
    assert record["level"] == ""


@pytest.mark.asyncio
async def test_add_group_message_does_not_wait_for_disk_save(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = MessageHistoryManager.__new__(MessageHistoryManager)
    manager._message_history = {}
    manager._max_records = 10000
    manager._initialized = asyncio.Event()
    manager._initialized.set()
    manager._group_locks = {}

    save_started = asyncio.Event()
    allow_save = asyncio.Event()
    saved_data: list[list[dict[str, object]]] = []

    async def fake_save(data: list[dict[str, object]], path: str) -> None:
        _ = path
        save_started.set()
        await allow_save.wait()
        saved_data.append(data)

    monkeypatch.setattr(manager, "_save_history_to_file", fake_save)

    await asyncio.wait_for(
        manager.add_group_message(
            group_id=20001,
            sender_id=10001,
            text_content="测试消息",
        ),
        timeout=1,
    )

    assert manager._message_history["20001"][0]["message"] == "测试消息"
    assert saved_data == []

    await asyncio.wait_for(save_started.wait(), timeout=1)
    allow_save.set()
    await manager.flush_pending_saves()

    assert saved_data[-1][0]["message"] == "测试消息"


@pytest.mark.asyncio
async def test_group_message_disk_saves_are_coalesced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = MessageHistoryManager.__new__(MessageHistoryManager)
    manager._message_history = {}
    manager._max_records = 10000
    manager._initialized = asyncio.Event()
    manager._initialized.set()
    manager._group_locks = {}

    first_save_started = asyncio.Event()
    allow_first_save = asyncio.Event()
    saved_messages: list[list[str]] = []

    async def fake_save(data: list[dict[str, object]], path: str) -> None:
        _ = path
        saved_messages.append([str(item["message"]) for item in data])
        if len(saved_messages) == 1:
            first_save_started.set()
            await allow_first_save.wait()

    monkeypatch.setattr(manager, "_save_history_to_file", fake_save)

    await manager.add_group_message(20001, 10001, "第一条")
    await asyncio.wait_for(first_save_started.wait(), timeout=1)
    await manager.add_group_message(20001, 10002, "第二条")
    await manager.add_group_message(20001, 10003, "第三条")

    allow_first_save.set()
    await manager.flush_pending_saves()

    assert saved_messages == [
        ["第一条"],
        ["第一条", "第二条", "第三条"],
    ]
