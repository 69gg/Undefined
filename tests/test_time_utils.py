"""Tests for Undefined.utils.time_utils — time parsing/formatting helpers."""

from __future__ import annotations

from datetime import datetime

from Undefined.utils.time_utils import format_datetime, parse_time_range


class TestParseTimeRange:
    def test_both_valid(self) -> None:
        start, end = parse_time_range("2024-01-15 08:30:00", "2024-06-20 17:45:00")
        assert start == datetime(2024, 1, 15, 8, 30, 0)
        assert end == datetime(2024, 6, 20, 17, 45, 0)

    def test_only_start(self) -> None:
        start, end = parse_time_range("2024-01-01 00:00:00", None)
        assert start == datetime(2024, 1, 1, 0, 0, 0)
        assert end is None

    def test_only_end(self) -> None:
        start, end = parse_time_range(None, "2024-12-31 23:59:59")
        assert start is None
        assert end == datetime(2024, 12, 31, 23, 59, 59)

    def test_both_none(self) -> None:
        start, end = parse_time_range(None, None)
        assert start is None
        assert end is None

    def test_invalid_start_format(self) -> None:
        start, end = parse_time_range("2024/01/01", None)
        assert start is None
        assert end is None

    def test_invalid_end_format(self) -> None:
        start, end = parse_time_range(None, "not-a-date")
        assert start is None
        assert end is None

    def test_both_invalid(self) -> None:
        start, end = parse_time_range("bad", "worse")
        assert start is None
        assert end is None

    def test_empty_strings(self) -> None:
        start, end = parse_time_range("", "")
        assert start is None
        assert end is None

    def test_date_only_format_rejected(self) -> None:
        start, end = parse_time_range("2024-01-01", None)
        assert start is None

    def test_midnight(self) -> None:
        start, end = parse_time_range("2024-01-01 00:00:00", None)
        assert start == datetime(2024, 1, 1, 0, 0, 0)

    def test_end_of_day(self) -> None:
        start, end = parse_time_range(None, "2024-12-31 23:59:59")
        assert end == datetime(2024, 12, 31, 23, 59, 59)


class TestFormatDatetime:
    def test_none_input(self) -> None:
        assert format_datetime(None) == "未指定"

    def test_normal_datetime(self) -> None:
        dt = datetime(2024, 3, 15, 14, 30, 45)
        assert format_datetime(dt) == "2024-03-15 14:30:45"

    def test_midnight(self) -> None:
        dt = datetime(2024, 1, 1, 0, 0, 0)
        assert format_datetime(dt) == "2024-01-01 00:00:00"

    def test_end_of_day(self) -> None:
        dt = datetime(2024, 12, 31, 23, 59, 59)
        assert format_datetime(dt) == "2024-12-31 23:59:59"

    def test_roundtrip(self) -> None:
        original = "2024-06-15 10:20:30"
        start, _ = parse_time_range(original, None)
        assert start is not None
        assert format_datetime(start) == original
