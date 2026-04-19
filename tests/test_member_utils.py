"""Tests for Undefined.utils.member_utils — member analysis helpers."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from Undefined.utils.member_utils import (
    analyze_join_trend,
    analyze_member_activity,
    filter_by_join_time,
)


def _make_member(
    user_id: int,
    join_time: int | float | None = None,
    card: str = "",
    nickname: str = "",
) -> dict[str, Any]:
    m: dict[str, Any] = {"user_id": user_id, "card": card, "nickname": nickname}
    if join_time is not None:
        m["join_time"] = join_time
    return m


# A fixed reference timestamp: 2024-06-15 12:00:00
_REF_TS = int(datetime(2024, 6, 15, 12, 0, 0).timestamp())
_DAY = 86400


class TestFilterByJoinTime:
    def test_empty_list(self) -> None:
        assert filter_by_join_time([], None, None) == []

    def test_no_filters(self) -> None:
        members = [_make_member(1, _REF_TS), _make_member(2, _REF_TS + _DAY)]
        result = filter_by_join_time(members, None, None)
        assert len(result) == 2

    def test_start_filter(self) -> None:
        members = [
            _make_member(1, _REF_TS - _DAY),
            _make_member(2, _REF_TS + _DAY),
        ]
        start_dt = datetime(2024, 6, 15, 0, 0, 0)
        result = filter_by_join_time(members, start_dt, None)
        assert len(result) == 1
        assert result[0]["user_id"] == 2

    def test_end_filter(self) -> None:
        members = [
            _make_member(1, _REF_TS - _DAY),
            _make_member(2, _REF_TS + _DAY),
        ]
        end_dt = datetime(2024, 6, 15, 0, 0, 0)
        result = filter_by_join_time(members, None, end_dt)
        assert len(result) == 1
        assert result[0]["user_id"] == 1

    def test_both_filters(self) -> None:
        members = [
            _make_member(1, _REF_TS - 2 * _DAY),
            _make_member(2, _REF_TS),
            _make_member(3, _REF_TS + 2 * _DAY),
        ]
        start_dt = datetime.fromtimestamp(_REF_TS - _DAY)
        end_dt = datetime.fromtimestamp(_REF_TS + _DAY)
        result = filter_by_join_time(members, start_dt, end_dt)
        assert len(result) == 1
        assert result[0]["user_id"] == 2

    def test_member_without_join_time_skipped(self) -> None:
        members = [_make_member(1), _make_member(2, _REF_TS)]
        result = filter_by_join_time(members, None, None)
        assert len(result) == 1
        assert result[0]["user_id"] == 2

    def test_non_numeric_join_time_skipped(self) -> None:
        members: list[dict[str, Any]] = [{"user_id": 1, "join_time": "not-a-number"}]
        result = filter_by_join_time(members, None, None)
        assert len(result) == 0

    def test_float_join_time(self) -> None:
        members = [_make_member(1, float(_REF_TS) + 0.5)]
        result = filter_by_join_time(members, None, None)
        assert len(result) == 1


class TestAnalyzeJoinTrend:
    def test_empty_list(self) -> None:
        assert analyze_join_trend([]) == {}

    def test_single_member(self) -> None:
        members = [_make_member(1, _REF_TS)]
        result = analyze_join_trend(members)
        assert result["peak_count"] == 1
        assert result["avg_per_day"] == 1.0
        assert result["first_time"] is not None
        assert result["last_time"] is not None
        assert result["first_time"] == result["last_time"]

    def test_multiple_members_same_day(self) -> None:
        members = [
            _make_member(1, _REF_TS),
            _make_member(2, _REF_TS + 3600),
        ]
        result = analyze_join_trend(members)
        assert result["peak_count"] == 2
        assert result["avg_per_day"] == 2.0

    def test_multiple_days(self) -> None:
        members = [
            _make_member(1, _REF_TS),
            _make_member(2, _REF_TS + _DAY),
            _make_member(3, _REF_TS + _DAY),
        ]
        result = analyze_join_trend(members)
        assert len(result["daily_stats"]) == 2
        assert result["peak_count"] == 2
        assert result["avg_per_day"] == 1.5

    def test_members_without_join_time_ignored(self) -> None:
        members = [_make_member(1), _make_member(2, _REF_TS)]
        result = analyze_join_trend(members)
        # Only one member has join_time, but total uses all members
        assert result["avg_per_day"] == 2.0  # 2 members / 1 day
        assert result["peak_count"] == 1

    def test_daily_stats_populated(self) -> None:
        members = [_make_member(1, _REF_TS)]
        result = analyze_join_trend(members)
        assert isinstance(result["daily_stats"], dict)
        assert len(result["daily_stats"]) == 1


class TestAnalyzeMemberActivity:
    def test_empty_members(self) -> None:
        result = analyze_member_activity([], {}, 5)
        assert result["total_members"] == 0
        assert result["active_members"] == 0
        assert result["total_messages"] == 0
        assert result["top_members"] == []

    def test_basic_activity(self) -> None:
        members = [
            _make_member(1, _REF_TS, nickname="Alice"),
            _make_member(2, _REF_TS, nickname="Bob"),
            _make_member(3, _REF_TS, nickname="Charlie"),
        ]
        counts: dict[int, int] = {1: 100, 2: 50, 3: 0}
        result = analyze_member_activity(members, counts, 5)
        assert result["total_members"] == 3
        assert result["active_members"] == 2
        assert result["inactive_members"] == 1
        assert result["total_messages"] == 150
        assert result["avg_messages"] == 50.0
        assert len(result["top_members"]) == 2
        assert result["top_members"][0]["user_id"] == 1

    def test_top_count_limit(self) -> None:
        members = [_make_member(i, _REF_TS) for i in range(1, 11)]
        counts: dict[int, int] = {i: i * 10 for i in range(1, 11)}
        result = analyze_member_activity(members, counts, 3)
        assert len(result["top_members"]) == 3
        assert result["top_members"][0]["user_id"] == 10

    def test_active_rate_calculation(self) -> None:
        members = [_make_member(1), _make_member(2)]
        counts: dict[int, int] = {1: 10, 2: 0}
        result = analyze_member_activity(members, counts, 5)
        assert result["active_rate"] == 50.0

    def test_zero_count_excluded_from_top(self) -> None:
        members = [_make_member(1, _REF_TS, nickname="A")]
        counts: dict[int, int] = {1: 0}
        result = analyze_member_activity(members, counts, 5)
        assert result["top_members"] == []

    def test_member_with_card_name(self) -> None:
        members = [_make_member(1, _REF_TS, card="CardName", nickname="Nick")]
        counts: dict[int, int] = {1: 10}
        result = analyze_member_activity(members, counts, 5)
        assert result["top_members"][0]["nickname"] == "CardName"

    def test_join_time_formatted_in_top(self) -> None:
        members = [_make_member(1, _REF_TS, nickname="A")]
        counts: dict[int, int] = {1: 5}
        result = analyze_member_activity(members, counts, 5)
        assert result["top_members"][0]["join_time"] != ""

    def test_no_join_time_empty_string(self) -> None:
        members = [_make_member(1, nickname="A")]
        counts: dict[int, int] = {1: 5}
        result = analyze_member_activity(members, counts, 5)
        assert result["top_members"][0]["join_time"] == ""
