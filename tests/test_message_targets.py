"""Tests for Undefined.utils.message_targets — target resolution helpers."""

from __future__ import annotations

from typing import Any

from Undefined.utils.message_targets import parse_positive_int, resolve_message_target


class TestParsePositiveInt:
    def test_valid_int(self) -> None:
        val, err = parse_positive_int(42, "field")
        assert val == 42
        assert err is None

    def test_valid_string_int(self) -> None:
        val, err = parse_positive_int("123", "field")
        assert val == 123
        assert err is None

    def test_none_input(self) -> None:
        val, err = parse_positive_int(None, "field")
        assert val is None
        assert err is None

    def test_zero_rejected(self) -> None:
        val, err = parse_positive_int(0, "field")
        assert val is None
        assert err is not None
        assert "正整数" in (err or "")

    def test_negative_rejected(self) -> None:
        val, err = parse_positive_int(-5, "field")
        assert val is None
        assert err is not None

    def test_non_numeric_string(self) -> None:
        val, err = parse_positive_int("abc", "field")
        assert val is None
        assert err is not None
        assert "整数" in (err or "")

    def test_float_truncated(self) -> None:
        val, err = parse_positive_int(3.9, "field")
        assert val == 3
        assert err is None

    def test_float_string_rejected(self) -> None:
        val, err = parse_positive_int("3.5", "field")
        assert val is None
        assert err is not None

    def test_bool_treated_as_int(self) -> None:
        # bool is subclass of int; True -> 1
        val, err = parse_positive_int(True, "field")
        assert val == 1
        assert err is None

    def test_field_name_in_error(self) -> None:
        _, err = parse_positive_int("bad", "target_id")
        assert err is not None
        assert "target_id" in err


class TestResolveMessageTarget:
    @staticmethod
    def _call(
        args: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
    ) -> tuple[tuple[str, int] | None, str | None]:
        result: tuple[tuple[str, int] | None, str | None] = resolve_message_target(
            args or {}, context or {}
        )
        return result

    def test_explicit_group_target(self) -> None:
        target, err = self._call(
            args={"target_type": "group", "target_id": 12345},
        )
        assert target == ("group", 12345)
        assert err is None

    def test_explicit_private_target(self) -> None:
        target, err = self._call(
            args={"target_type": "private", "target_id": 67890},
        )
        assert target == ("private", 67890)
        assert err is None

    def test_target_type_case_insensitive(self) -> None:
        target, err = self._call(
            args={"target_type": "GROUP", "target_id": 1},
        )
        assert target == ("group", 1)

    def test_target_type_without_id_infers_from_context(self) -> None:
        target, err = self._call(
            args={"target_type": "group"},
            context={"request_type": "group", "group_id": 100},
        )
        assert target == ("group", 100)
        assert err is None

    def test_target_type_without_id_mismatch_context(self) -> None:
        target, err = self._call(
            args={"target_type": "group"},
            context={"request_type": "private", "user_id": 100},
        )
        assert target is None
        assert err is not None
        assert "不一致" in (err or "")

    def test_target_id_without_type_error(self) -> None:
        target, err = self._call(args={"target_id": 123})
        assert target is None
        assert err is not None
        assert "同时提供" in (err or "")

    def test_invalid_target_type(self) -> None:
        target, err = self._call(
            args={"target_type": "channel", "target_id": 1},
        )
        assert target is None
        assert err is not None

    def test_target_type_non_string(self) -> None:
        target, err = self._call(
            args={"target_type": 123, "target_id": 1},
        )
        assert target is None
        assert err is not None
        assert "字符串" in (err or "")

    def test_legacy_group_id(self) -> None:
        target, err = self._call(args={"group_id": 999})
        assert target == ("group", 999)
        assert err is None

    def test_legacy_user_id(self) -> None:
        target, err = self._call(args={"user_id": 888})
        assert target == ("private", 888)
        assert err is None

    def test_legacy_invalid_group_id(self) -> None:
        target, err = self._call(args={"group_id": -1})
        assert target is None
        assert err is not None

    def test_fallback_to_context_group(self) -> None:
        target, err = self._call(
            context={"request_type": "group", "group_id": 555},
        )
        assert target == ("group", 555)
        assert err is None

    def test_fallback_to_context_private(self) -> None:
        target, err = self._call(
            context={"request_type": "private", "user_id": 444},
        )
        assert target == ("private", 444)
        assert err is None

    def test_fallback_context_group_id_only(self) -> None:
        target, err = self._call(context={"group_id": 333})
        assert target == ("group", 333)
        assert err is None

    def test_fallback_context_user_id_only(self) -> None:
        target, err = self._call(context={"user_id": 222})
        assert target == ("private", 222)
        assert err is None

    def test_no_target_info_at_all(self) -> None:
        target, err = self._call()
        assert target is None
        assert err is not None
        assert "无法确定" in (err or "")

    def test_target_type_private_infer_from_context(self) -> None:
        target, err = self._call(
            args={"target_type": "private"},
            context={"request_type": "private", "user_id": 77},
        )
        assert target == ("private", 77)
        assert err is None
