from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from unittest.mock import MagicMock

import pytest

from Undefined.skills.agents.summary_agent.tools.fetch_messages.handler import (
    _filter_by_time,
    _format_messages,
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


def test_format_messages_basic() -> None:
    """Basic formatting with timestamp, name, and message."""
    messages = [
        {
            "timestamp": "2024-01-01 12:00:00",
            "display_name": "Alice",
            "message": "Hello",
            "role": "",
            "title": "",
        },
    ]

    result = _format_messages(messages)
    assert result == "[2024-01-01 12:00:00] Alice: Hello"


def test_format_messages_with_role() -> None:
    """Role is included when not 'member' or empty."""
    messages = [
        {
            "timestamp": "2024-01-01 12:00:00",
            "display_name": "Bob",
            "message": "Hi",
            "role": "admin",
            "title": "",
        },
    ]

    result = _format_messages(messages)
    assert result == "[2024-01-01 12:00:00] (admin) Bob: Hi"


def test_format_messages_with_title() -> None:
    """Title is included when present."""
    messages = [
        {
            "timestamp": "2024-01-01 12:00:00",
            "display_name": "Charlie",
            "message": "Test",
            "role": "",
            "title": "群主",
        },
    ]

    result = _format_messages(messages)
    assert result == "[2024-01-01 12:00:00] [群主] Charlie: Test"


def test_format_messages_with_title_and_role() -> None:
    """Both title and role are included."""
    messages = [
        {
            "timestamp": "2024-01-01 12:00:00",
            "display_name": "Dave",
            "message": "Message",
            "role": "owner",
            "title": "管理员",
        },
    ]

    result = _format_messages(messages)
    assert result == "[2024-01-01 12:00:00] [管理员] (owner) Dave: Message"


def test_format_messages_role_member_excluded() -> None:
    """Role 'member' is not included."""
    messages = [
        {
            "timestamp": "2024-01-01 12:00:00",
            "display_name": "Eve",
            "message": "Text",
            "role": "member",
            "title": "",
        },
    ]

    result = _format_messages(messages)
    assert result == "[2024-01-01 12:00:00] Eve: Text"


def test_format_messages_multiple() -> None:
    """Multiple messages are separated by newlines."""
    messages = [
        {
            "timestamp": "2024-01-01 12:00:00",
            "display_name": "Alice",
            "message": "First",
            "role": "",
            "title": "",
        },
        {
            "timestamp": "2024-01-01 12:01:00",
            "display_name": "Bob",
            "message": "Second",
            "role": "admin",
            "title": "",
        },
    ]

    result = _format_messages(messages)
    expected = (
        "[2024-01-01 12:00:00] Alice: First\n[2024-01-01 12:01:00] (admin) Bob: Second"
    )
    assert result == expected


def test_format_messages_missing_fields() -> None:
    """Missing fields default to empty or '未知用户'."""
    messages = [
        {
            "timestamp": "",
            "message": "No timestamp",
        },
    ]

    result = _format_messages(messages)
    assert "未知用户" in result
    assert "No timestamp" in result


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
    assert "Alice: Message 1" in result
    assert "Bob: Message 2" in result
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
    assert "Private message" in result
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
    assert "Recent" in result
    assert "Old" not in result


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
