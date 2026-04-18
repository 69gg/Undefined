from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from unittest.mock import MagicMock

import pytest

from Undefined.skills.agents.summary_agent.tools.fetch_messages.handler import (
    _filter_by_time,
    _format_messages,
    _format_message_xml,
    _parse_time_range,
    execute as fetch_messages_execute,
)


# -- _parse_time_range unit tests --


def test_parse_time_range_1h() -> None:
    """'1h' → 3600."""
    assert _parse_time_range("1h") == 3600


def test_parse_time_range_6h() -> None:
    """'6h' → 21600."""
    assert _parse_time_range("6h") == 21600


def test_parse_time_range_1d() -> None:
    """'1d' → 86400."""
    assert _parse_time_range("1d") == 86400


def test_parse_time_range_7d() -> None:
    """'7d' → 604800."""
    assert _parse_time_range("7d") == 604800


def test_parse_time_range_1w() -> None:
    """'1w' → 604800."""
    assert _parse_time_range("1w") == 604800


def test_parse_time_range_case_insensitive() -> None:
    """'1H', '1D' → correct values."""
    assert _parse_time_range("1H") == 3600
    assert _parse_time_range("1D") == 86400
    assert _parse_time_range("1W") == 604800


def test_parse_time_range_invalid() -> None:
    """'invalid' → None."""
    assert _parse_time_range("invalid") is None
    assert _parse_time_range("") is None
    assert _parse_time_range("abc") is None
    assert _parse_time_range("1x") is None


def test_parse_time_range_with_whitespace() -> None:
    """'  1d  ' → 86400 (strips whitespace)."""
    assert _parse_time_range("  1d  ") == 86400


def test_parse_time_range_multi_digit() -> None:
    """'24h' → 86400."""
    assert _parse_time_range("24h") == 86400


# -- _filter_by_time unit tests --


def test_filter_by_time_keeps_recent() -> None:
    """Messages within time range are kept."""
    now = datetime.now()
    recent = (now - timedelta(seconds=1800)).strftime("%Y-%m-%d %H:%M:%S")
    old = (now - timedelta(seconds=7200)).strftime("%Y-%m-%d %H:%M:%S")

    messages = [
        {"timestamp": recent, "message": "recent"},
        {"timestamp": old, "message": "old"},
    ]

    result = _filter_by_time(messages, 3600)  # 1 hour
    assert len(result) == 1
    assert result[0]["message"] == "recent"


def test_filter_by_time_removes_old() -> None:
    """Messages outside time range are removed."""
    now = datetime.now()
    old1 = (now - timedelta(days=2)).strftime("%Y-%m-%d %H:%M:%S")
    old2 = (now - timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S")

    messages = [
        {"timestamp": old1, "message": "old1"},
        {"timestamp": old2, "message": "old2"},
    ]

    result = _filter_by_time(messages, 86400)  # 1 day
    assert len(result) == 0


def test_filter_by_time_missing_timestamp() -> None:
    """Messages without timestamp are filtered out."""
    messages = [
        {"message": "no timestamp"},
        {"timestamp": "", "message": "empty timestamp"},
    ]

    result = _filter_by_time(messages, 3600)
    assert len(result) == 0


def test_filter_by_time_invalid_timestamp() -> None:
    """Messages with invalid timestamp format are filtered out."""
    messages = [
        {"timestamp": "invalid-format", "message": "bad format"},
        {"timestamp": "2024-13-45 99:99:99", "message": "impossible date"},
    ]

    result = _filter_by_time(messages, 3600)
    assert len(result) == 0


# -- _format_messages unit tests --


def test_format_message_xml_group_basic() -> None:
    """Group message is formatted into main-AI-compatible XML."""
    messages = [
        {
            "type": "group",
            "chat_id": "123456",
            "chat_name": "测试群",
            "timestamp": "2024-01-01 12:00:00",
            "display_name": "Alice",
            "user_id": "10001",
            "message": "Hello",
            "role": "member",
            "title": "群主",
            "level": "42",
            "message_id": 123,
        },
    ]

    result = _format_message_xml(messages[0])
    assert 'message_id="123"' in result
    assert 'sender="Alice"' in result
    assert 'sender_id="10001"' in result
    assert 'group_id="123456"' in result
    assert 'group_name="测试群"' in result
    assert 'location="测试群"' in result
    assert 'role="member"' in result
    assert 'title="群主"' in result
    assert 'level="42"' in result
    assert "<content>Hello</content>" in result


def test_format_message_xml_private_basic() -> None:
    """Private message uses the private XML shape."""
    msg = {
        "type": "private",
        "timestamp": "2024-01-01 12:00:00",
        "display_name": "Bob",
        "user_id": "10002",
        "message": "Hi",
        "message_id": 456,
    }

    result = _format_message_xml(msg)
    assert 'message_id="456"' in result
    assert 'sender="Bob"' in result
    assert 'sender_id="10002"' in result
    assert 'location="私聊"' in result
    assert "group_id=" not in result
    assert "role=" not in result
    assert "<content>Hi</content>" in result


def test_format_message_xml_includes_attachments() -> None:
    """Attachment refs are rendered as XML below content."""
    msg = {
        "type": "group",
        "chat_id": "123456",
        "chat_name": "测试群",
        "timestamp": "2024-01-01 12:00:00",
        "display_name": "Charlie",
        "user_id": "10003",
        "message": "看这个",
        "attachments": [
            {
                "uid": "pic_abcd1234",
                "kind": "image",
                "media_type": "image",
                "display_name": "a.png",
                "description": "截图",
            }
        ],
    }

    result = _format_message_xml(msg)
    assert "<attachments>" in result
    assert 'uid="pic_abcd1234"' in result
    assert 'type="image"' in result
    assert 'description="截图"' in result


def test_format_messages_multiple() -> None:
    """Multiple messages are separated by main-AI-style delimiters."""
    messages = [
        {
            "type": "group",
            "chat_id": "123456",
            "chat_name": "测试群",
            "timestamp": "2024-01-01 12:00:00",
            "display_name": "Alice",
            "user_id": "10001",
            "message": "First",
        },
        {
            "type": "private",
            "timestamp": "2024-01-01 12:00:00",
            "display_name": "Bob",
            "user_id": "10002",
            "message": "Second",
        },
    ]

    result = _format_messages(messages)
    assert "\n---\n" in result
    assert result.count("<message") == 2


def test_format_messages_missing_fields() -> None:
    """Missing fields still produce valid XML."""
    messages = [
        {
            "timestamp": "",
            "message": "No timestamp",
        },
    ]

    result = _format_messages(messages)
    assert "未知用户" in result
    assert "No timestamp" in result
    assert "<message" in result


# -- execute function tests --


@pytest.mark.asyncio
async def test_fetch_messages_count_based_group() -> None:
    """Count-based fetch in group context."""
    history_manager = MagicMock()
    history_manager.get_recent.return_value = [
        {
            "timestamp": "2024-01-01 12:00:00",
            "display_name": "Alice",
            "message": "Message 1",
            "role": "",
            "title": "",
        },
        {
            "timestamp": "2024-01-01 12:01:00",
            "display_name": "Bob",
            "message": "Message 2",
            "role": "",
            "title": "",
        },
    ]

    context: dict[str, Any] = {
        "history_manager": history_manager,
        "group_id": 123456,
        "user_id": 0,
    }

    result = await fetch_messages_execute({"count": 50}, context)

    assert "共获取 2 条消息" in result
    assert 'sender="Alice"' in result
    assert "<content>Message 1</content>" in result
    assert 'sender="Bob"' in result
    assert "<content>Message 2</content>" in result
    history_manager.get_recent.assert_called_once_with("123456", "group", 0, 50)


@pytest.mark.asyncio
async def test_fetch_messages_count_based_private() -> None:
    """Count-based fetch in private context."""
    history_manager = MagicMock()
    history_manager.get_recent.return_value = [
        {
            "timestamp": "2024-01-01 12:00:00",
            "display_name": "User",
            "message": "Private message",
            "role": "",
            "title": "",
        },
    ]

    context: dict[str, Any] = {
        "history_manager": history_manager,
        "group_id": 0,
        "user_id": 99999,
    }

    result = await fetch_messages_execute({"count": 20}, context)

    assert "共获取 1 条消息" in result
    assert 'location="私聊"' in result
    assert "<content>Private message</content>" in result
    history_manager.get_recent.assert_called_once_with("99999", "private", 0, 20)


@pytest.mark.asyncio
async def test_fetch_messages_time_range() -> None:
    """Time-range fetch filters by time."""
    now = datetime.now()
    recent = (now - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
    old = (now - timedelta(hours=25)).strftime("%Y-%m-%d %H:%M:%S")

    history_manager = MagicMock()
    history_manager.get_recent.return_value = [
        {
            "timestamp": recent,
            "display_name": "Alice",
            "message": "Recent",
            "role": "",
            "title": "",
        },
        {
            "timestamp": old,
            "display_name": "Bob",
            "message": "Old",
            "role": "",
            "title": "",
        },
    ]

    context: dict[str, Any] = {
        "history_manager": history_manager,
        "group_id": 123456,
        "user_id": 0,
    }

    result = await fetch_messages_execute(
        {"count": 50, "time_range": "1d"},
        context,
    )

    assert "共获取 1 条消息" in result
    assert "(时间范围: 1d)" in result
    assert "<content>Recent</content>" in result
    assert "<content>Old</content>" not in result


@pytest.mark.asyncio
async def test_fetch_messages_invalid_time_range() -> None:
    """Invalid time range returns error message."""
    context: dict[str, Any] = {
        "history_manager": MagicMock(),
        "group_id": 123456,
    }

    result = await fetch_messages_execute(
        {"time_range": "invalid"},
        context,
    )

    assert "无法解析时间范围: invalid" in result
    assert "支持格式: 1h, 6h, 1d, 7d" in result


@pytest.mark.asyncio
async def test_fetch_messages_empty_history() -> None:
    """Empty history returns '当前会话暂无消息记录'."""
    history_manager = MagicMock()
    history_manager.get_recent.return_value = []

    context: dict[str, Any] = {
        "history_manager": history_manager,
        "group_id": 123456,
    }

    result = await fetch_messages_execute({}, context)

    assert "当前会话暂无消息记录" in result


@pytest.mark.asyncio
async def test_fetch_messages_no_history_manager() -> None:
    """No history_manager returns error."""
    context: dict[str, Any] = {
        "group_id": 123456,
    }

    result = await fetch_messages_execute({}, context)

    assert "历史记录管理器未配置" in result


@pytest.mark.asyncio
async def test_fetch_messages_count_capped_at_500() -> None:
    """Count is capped at 500."""
    history_manager = MagicMock()
    history_manager.get_recent.return_value = []

    context: dict[str, Any] = {
        "history_manager": history_manager,
        "group_id": 123456,
    }

    await fetch_messages_execute({"count": 9999}, context)

    history_manager.get_recent.assert_called_once_with("123456", "group", 0, 500)


@pytest.mark.asyncio
async def test_fetch_messages_default_count() -> None:
    """Default count is 50 when not specified."""
    history_manager = MagicMock()
    history_manager.get_recent.return_value = []

    context: dict[str, Any] = {
        "history_manager": history_manager,
        "group_id": 123456,
    }

    await fetch_messages_execute({}, context)

    history_manager.get_recent.assert_called_once_with("123456", "group", 0, 50)


@pytest.mark.asyncio
async def test_fetch_messages_invalid_count_defaults() -> None:
    """Invalid count defaults to 50."""
    history_manager = MagicMock()
    history_manager.get_recent.return_value = []

    context: dict[str, Any] = {
        "history_manager": history_manager,
        "group_id": 123456,
    }

    await fetch_messages_execute({"count": "invalid"}, context)

    history_manager.get_recent.assert_called_once_with("123456", "group", 0, 50)


@pytest.mark.asyncio
async def test_fetch_messages_time_range_fetch_larger_batch() -> None:
    """Time range mode fetches larger batch (max(count*2, 2000))."""
    history_manager = MagicMock()
    history_manager.get_recent.return_value = []

    context: dict[str, Any] = {
        "history_manager": history_manager,
        "group_id": 123456,
    }

    await fetch_messages_execute(
        {"count": 50, "time_range": "1d"},
        context,
    )

    # max(50*2, 2000) = 2000
    history_manager.get_recent.assert_called_once_with("123456", "group", 0, 2000)
