"""Tests for Undefined.utils.message_utils."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict

import pytest

from Undefined.utils.message_utils import (
    analyze_activity_pattern,
    count_message_types,
    count_messages_by_user,
    filter_user_messages,
    format_messages,
)


@pytest.fixture(autouse=True)
def _mock_parse_message_time(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch parse_message_time so tests don't depend on onebot imports."""

    def _fake_parse(msg: Dict[str, Any]) -> datetime:
        return datetime.fromtimestamp(msg.get("time", 0))

    monkeypatch.setattr(
        "Undefined.utils.message_utils.parse_message_time",
        _fake_parse,
    )


def _msg(
    user_id: int = 100,
    ts: int = 1700000000,
    message: Any = None,
    nickname: str = "TestUser",
) -> Dict[str, Any]:
    """Helper to build a minimal message dict."""
    return {
        "sender": {"user_id": user_id, "nickname": nickname},
        "time": ts,
        "message": message if message is not None else "hello",
    }


# ---------------------------------------------------------------------------
# filter_user_messages
# ---------------------------------------------------------------------------


class TestFilterUserMessages:
    def test_filters_by_user_id(self) -> None:
        msgs = [_msg(user_id=1), _msg(user_id=2), _msg(user_id=1)]
        result = filter_user_messages(msgs, user_id=1, start_dt=None, end_dt=None)
        assert len(result) == 2

    def test_filters_by_time_range(self) -> None:
        msgs = [
            _msg(ts=1700000000),
            _msg(ts=1700000100),
            _msg(ts=1700000200),
        ]
        start = datetime.fromtimestamp(1700000050)
        end = datetime.fromtimestamp(1700000150)
        result = filter_user_messages(msgs, user_id=100, start_dt=start, end_dt=end)
        assert len(result) == 1

    def test_empty_messages(self) -> None:
        result = filter_user_messages([], user_id=1, start_dt=None, end_dt=None)
        assert result == []

    def test_no_time_bounds(self) -> None:
        msgs = [_msg(user_id=100, ts=1700000000)]
        result = filter_user_messages(msgs, user_id=100, start_dt=None, end_dt=None)
        assert len(result) == 1


# ---------------------------------------------------------------------------
# count_message_types
# ---------------------------------------------------------------------------


class TestCountMessageTypes:
    def test_string_message_is_text(self) -> None:
        msgs = [_msg(message="hi")]
        result = count_message_types(msgs)
        assert result == {"文本消息": 1}

    def test_image_segment(self) -> None:
        msgs = [_msg(message=[{"type": "image", "data": {}}])]
        result = count_message_types(msgs)
        assert result == {"图片消息": 1}

    def test_reply_priority_over_text(self) -> None:
        msgs = [
            _msg(
                message=[
                    {"type": "reply", "data": {}},
                    {"type": "text", "data": {"text": "hi"}},
                ]
            )
        ]
        result = count_message_types(msgs)
        assert result == {"回复消息": 1}

    def test_face_segment(self) -> None:
        msgs = [_msg(message=[{"type": "face", "data": {}}])]
        result = count_message_types(msgs)
        assert result == {"表情消息": 1}

    def test_empty_segment_list(self) -> None:
        msgs: list[Dict[str, Any]] = [_msg(message=[])]
        result = count_message_types(msgs)
        assert result == {"空消息": 1}

    def test_other_segment_type(self) -> None:
        msgs = [_msg(message=[{"type": "forward", "data": {}}])]
        result = count_message_types(msgs)
        assert result == {"其他消息": 1}

    def test_text_only_segments(self) -> None:
        msgs = [_msg(message=[{"type": "text", "data": {"text": "hello"}}])]
        result = count_message_types(msgs)
        assert result == {"文本消息": 1}

    def test_mixed_messages(self) -> None:
        msgs = [
            _msg(message="hi"),
            _msg(message=[{"type": "image", "data": {}}]),
            _msg(message=[{"type": "face", "data": {}}]),
        ]
        result = count_message_types(msgs)
        assert result == {"文本消息": 1, "图片消息": 1, "表情消息": 1}


# ---------------------------------------------------------------------------
# analyze_activity_pattern
# ---------------------------------------------------------------------------


class TestAnalyzeActivityPattern:
    def test_empty_returns_empty_dict(self) -> None:
        assert analyze_activity_pattern([]) == {}

    def test_single_message(self) -> None:
        ts = 1700000000
        msgs = [_msg(ts=ts)]
        result = analyze_activity_pattern(msgs)
        assert result["avg_per_day"] == 1.0
        assert result["first_time"] is not None
        assert result["last_time"] is not None
        assert result["first_time"] == result["last_time"]

    def test_multiple_messages_avg_per_day(self) -> None:
        # Two messages on the same day
        msgs = [_msg(ts=1700000000), _msg(ts=1700000100)]
        result = analyze_activity_pattern(msgs)
        assert result["avg_per_day"] == 2.0

    def test_most_active_hour_format(self) -> None:
        msgs = [_msg(ts=1700000000)]
        result = analyze_activity_pattern(msgs)
        hour_str: str = result["most_active_hour"]
        assert ":00-" in hour_str
        assert ":59" in hour_str

    def test_weekday_is_chinese(self) -> None:
        msgs = [_msg(ts=1700000000)]
        result = analyze_activity_pattern(msgs)
        weekday_str: str = result["most_active_weekday"]
        assert weekday_str.startswith("周")


# ---------------------------------------------------------------------------
# count_messages_by_user
# ---------------------------------------------------------------------------


class TestCountMessagesByUser:
    def test_counts_correctly(self) -> None:
        msgs = [_msg(user_id=1), _msg(user_id=2), _msg(user_id=1)]
        result = count_messages_by_user(msgs, {1, 2, 3})
        assert result == {1: 2, 2: 1, 3: 0}

    def test_unknown_user_ignored(self) -> None:
        msgs = [_msg(user_id=99)]
        result = count_messages_by_user(msgs, {1})
        assert result == {1: 0}

    def test_empty_messages(self) -> None:
        result = count_messages_by_user([], {1, 2})
        assert result == {1: 0, 2: 0}


# ---------------------------------------------------------------------------
# format_messages
# ---------------------------------------------------------------------------


class TestFormatMessages:
    def test_basic_format(self) -> None:
        msgs = [_msg(user_id=42, ts=1700000000, nickname="Alice")]
        result = format_messages(msgs)
        assert len(result) == 1
        assert result[0]["sender"] == "Alice"
        assert result[0]["sender_id"] == 42
        assert "2023" in result[0]["time"]
        assert result[0]["content"] == "hello"

    def test_segment_format(self) -> None:
        msg = _msg(
            message=[
                {"type": "text", "data": {"text": "hi "}},
                {"type": "image", "data": {}},
            ]
        )
        result = format_messages([msg])
        assert result[0]["content"] == "hi [图片]"

    def test_empty_content_placeholder(self) -> None:
        msg = _msg(message=[])
        result = format_messages([msg])
        assert result[0]["content"] == "(空消息)"

    def test_card_preferred_over_nickname(self) -> None:
        msg: Dict[str, Any] = {
            "sender": {"user_id": 1, "card": "CardName", "nickname": "Nick"},
            "time": 1700000000,
            "message": "hi",
        }
        result = format_messages([msg])
        assert result[0]["sender"] == "CardName"
