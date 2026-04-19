"""Tests for Undefined.utils.group_metrics — group member metric helpers."""

from __future__ import annotations

from datetime import datetime

from Undefined.utils.group_metrics import (
    clamp_int,
    datetime_to_ts,
    format_timestamp,
    member_display_name,
    parse_member_level,
    parse_unix_timestamp,
    role_to_cn,
)


class TestClampInt:
    def test_within_range(self) -> None:
        assert clamp_int(5, 0, 1, 10) == 5

    def test_below_min(self) -> None:
        assert clamp_int(-5, 0, 1, 10) == 1

    def test_above_max(self) -> None:
        assert clamp_int(20, 0, 1, 10) == 10

    def test_at_min(self) -> None:
        assert clamp_int(1, 0, 1, 10) == 1

    def test_at_max(self) -> None:
        assert clamp_int(10, 0, 1, 10) == 10

    def test_non_numeric_returns_default(self) -> None:
        assert clamp_int("abc", 7, 1, 10) == 7

    def test_none_returns_default(self) -> None:
        assert clamp_int(None, 5, 1, 10) == 5

    def test_string_int(self) -> None:
        assert clamp_int("3", 0, 1, 10) == 3

    def test_float_truncated(self) -> None:
        assert clamp_int(3.9, 0, 1, 10) == 3

    def test_bool_as_int(self) -> None:
        assert clamp_int(True, 0, 0, 10) == 1


class TestParseUnixTimestamp:
    def test_valid_positive(self) -> None:
        assert parse_unix_timestamp(1700000000) == 1700000000

    def test_zero(self) -> None:
        assert parse_unix_timestamp(0) == 0

    def test_negative(self) -> None:
        assert parse_unix_timestamp(-100) == 0

    def test_none(self) -> None:
        assert parse_unix_timestamp(None) == 0

    def test_non_numeric(self) -> None:
        assert parse_unix_timestamp("abc") == 0

    def test_string_number(self) -> None:
        assert parse_unix_timestamp("1700000000") == 1700000000

    def test_float(self) -> None:
        assert parse_unix_timestamp(1700000000.5) == 1700000000


class TestParseMemberLevel:
    def test_integer(self) -> None:
        assert parse_member_level(5) == 5

    def test_zero(self) -> None:
        assert parse_member_level(0) == 0

    def test_negative_int(self) -> None:
        assert parse_member_level(-1) is None

    def test_none(self) -> None:
        assert parse_member_level(None) is None

    def test_bool_returns_none(self) -> None:
        assert parse_member_level(True) is None
        assert parse_member_level(False) is None

    def test_float(self) -> None:
        assert parse_member_level(3.7) == 3

    def test_digit_string(self) -> None:
        assert parse_member_level("10") == 10

    def test_string_with_digits(self) -> None:
        assert parse_member_level("Lv.5") == 5

    def test_string_no_digits(self) -> None:
        assert parse_member_level("无") is None

    def test_empty_string(self) -> None:
        assert parse_member_level("") is None

    def test_whitespace_string(self) -> None:
        assert parse_member_level("  ") is None

    def test_complex_string(self) -> None:
        assert parse_member_level("等级42勋章") == 42


class TestMemberDisplayName:
    def test_card_preferred(self) -> None:
        member = {"card": "CardName", "nickname": "Nick", "user_id": 123}
        assert member_display_name(member) == "CardName"

    def test_nickname_fallback(self) -> None:
        member = {"card": "", "nickname": "Nick", "user_id": 123}
        assert member_display_name(member) == "Nick"

    def test_user_id_fallback(self) -> None:
        member = {"card": "", "nickname": "", "user_id": 123}
        assert member_display_name(member) == "123"

    def test_none_card(self) -> None:
        member = {"card": None, "nickname": "Nick"}
        assert member_display_name(member) == "Nick"

    def test_all_missing(self) -> None:
        member: dict[str, object] = {}
        assert member_display_name(member) == "未知"

    def test_whitespace_card(self) -> None:
        member = {"card": "  ", "nickname": "Nick"}
        assert member_display_name(member) == "Nick"


class TestRoleToCn:
    def test_owner(self) -> None:
        assert role_to_cn("owner") == "群主"

    def test_admin(self) -> None:
        assert role_to_cn("admin") == "管理员"

    def test_member(self) -> None:
        assert role_to_cn("member") == "成员"

    def test_none_defaults_to_member(self) -> None:
        assert role_to_cn(None) == "成员"

    def test_unknown_role_passthrough(self) -> None:
        assert role_to_cn("moderator") == "moderator"

    def test_empty_string_defaults_to_member(self) -> None:
        # str("" or "member") -> "member"
        assert role_to_cn("") == "成员"


class TestFormatTimestamp:
    def test_valid_timestamp(self) -> None:
        ts = int(datetime(2024, 1, 15, 12, 0, 0).timestamp())
        result = format_timestamp(ts)
        assert "2024-01-15" in result

    def test_zero(self) -> None:
        assert format_timestamp(0) == "无"

    def test_negative(self) -> None:
        assert format_timestamp(-1) == "无"

    def test_overflow(self) -> None:
        assert format_timestamp(999999999999999) == "无"


class TestDatetimeToTs:
    def test_none(self) -> None:
        assert datetime_to_ts(None) is None

    def test_valid_datetime(self) -> None:
        dt = datetime(2024, 6, 15, 12, 0, 0)
        result = datetime_to_ts(dt)
        assert result is not None
        assert isinstance(result, int)
        # Round-trip check
        assert datetime.fromtimestamp(result).replace(second=0) == dt.replace(second=0)

    def test_epoch(self) -> None:
        dt = datetime(1970, 1, 1, 0, 0, 0)
        result = datetime_to_ts(dt)
        assert result is not None
