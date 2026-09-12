from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest

from Undefined.onebot import parse_message_time, try_parse_message_time


@pytest.mark.parametrize(
    ("raw_time", "expected_seconds"),
    [
        (1_700_000_000, 1_700_000_000),
        (1_700_000_000.125, 1_700_000_000.125),
        ("1700000000", 1_700_000_000),
        ("1700000000.125", 1_700_000_000.125),
        (1_700_000_000_000, 1_700_000_000),
        ("1700000000125", 1_700_000_000.125),
    ],
)
def test_message_time_parsers_preserve_supported_timestamps(
    raw_time: int | float | str, expected_seconds: float
) -> None:
    """严格解析和兼容解析都保留秒、毫秒与数值字符串的真实时间。"""
    message = {"time": raw_time}
    expected = datetime.fromtimestamp(expected_seconds)

    assert try_parse_message_time(message) == expected
    assert parse_message_time(message) == expected


@pytest.mark.parametrize(
    "message",
    [
        {},
        {"time": None},
        {"time": 0},
        {"time": -1},
        {"time": "invalid-time"},
        {"time": 1e30},
        {"time": 10**400},
        {"time": "nan"},
        {"time": "inf"},
        {"time": True},
        {"time": False},
        {"time": []},
    ],
)
def test_invalid_message_times_remain_unknown_without_breaking_legacy_fallback(
    message: dict[str, Any],
) -> None:
    """统计解析保留无效状态，原接口仍为展示场景回退到当前时间。"""
    assert try_parse_message_time(message) is None

    before = datetime.now()
    parsed = parse_message_time(message)
    after = datetime.now()
    assert before <= parsed <= after
