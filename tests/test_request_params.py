"""Tests for Undefined.utils.request_params — request param helpers."""

from __future__ import annotations

from collections import OrderedDict
from typing import Any

from Undefined.utils.request_params import (
    merge_request_params,
    normalize_request_params,
    split_reserved_request_params,
)


class TestNormalizeRequestParams:
    def test_dict_passthrough(self) -> None:
        result = normalize_request_params({"a": 1, "b": "two"})
        assert result == {"a": 1, "b": "two"}

    def test_none_returns_empty(self) -> None:
        assert normalize_request_params(None) == {}

    def test_non_dict_returns_empty(self) -> None:
        assert normalize_request_params("string") == {}
        assert normalize_request_params(42) == {}
        assert normalize_request_params([1, 2]) == {}

    def test_empty_dict(self) -> None:
        assert normalize_request_params({}) == {}

    def test_nested_dict_cloned(self) -> None:
        original: dict[str, Any] = {"inner": {"x": 1}}
        result = normalize_request_params(original)
        assert result == {"inner": {"x": 1}}
        # Must be a deep copy
        assert result["inner"] is not original["inner"]

    def test_list_cloned(self) -> None:
        original: dict[str, Any] = {"items": [1, 2, {"a": 3}]}
        result = normalize_request_params(original)
        assert result["items"] == [1, 2, {"a": 3}]
        assert result["items"] is not original["items"]

    def test_tuple_converted_to_list(self) -> None:
        result = normalize_request_params({"t": (1, 2, 3)})
        assert result["t"] == [1, 2, 3]
        assert isinstance(result["t"], list)

    def test_non_json_value_stringified(self) -> None:
        result = normalize_request_params({"obj": object()})
        assert isinstance(result["obj"], str)

    def test_keys_stringified(self) -> None:
        result = normalize_request_params({1: "a", 2: "b"})
        assert "1" in result
        assert "2" in result

    def test_ordered_dict_accepted(self) -> None:
        od = OrderedDict([("z", 1), ("a", 2)])
        result = normalize_request_params(od)
        assert result == {"z": 1, "a": 2}

    def test_bool_preserved(self) -> None:
        result = normalize_request_params({"flag": True})
        assert result["flag"] is True

    def test_none_value_preserved(self) -> None:
        result = normalize_request_params({"key": None})
        assert result["key"] is None


class TestMergeRequestParams:
    def test_single_dict(self) -> None:
        result = merge_request_params({"a": 1})
        assert result == {"a": 1}

    def test_two_dicts_merged(self) -> None:
        result = merge_request_params({"a": 1}, {"b": 2})
        assert result == {"a": 1, "b": 2}

    def test_later_overrides_earlier(self) -> None:
        result = merge_request_params({"a": 1}, {"a": 2})
        assert result["a"] == 2

    def test_none_skipped(self) -> None:
        result = merge_request_params(None, {"a": 1})
        assert result == {"a": 1}

    def test_non_dict_skipped(self) -> None:
        result = merge_request_params("bad", {"a": 1}, 42)
        assert result == {"a": 1}

    def test_empty_args(self) -> None:
        result = merge_request_params()
        assert result == {}

    def test_multiple_merges(self) -> None:
        result = merge_request_params({"a": 1}, {"b": 2}, {"c": 3})
        assert result == {"a": 1, "b": 2, "c": 3}


class TestSplitReservedRequestParams:
    def test_basic_split(self) -> None:
        allowed, reserved = split_reserved_request_params(
            {"a": 1, "b": 2, "c": 3}, {"b", "c"}
        )
        assert allowed == {"a": 1}
        assert reserved == {"b": 2, "c": 3}

    def test_no_reserved_keys(self) -> None:
        allowed, reserved = split_reserved_request_params({"a": 1}, set())
        assert allowed == {"a": 1}
        assert reserved == {}

    def test_all_reserved(self) -> None:
        allowed, reserved = split_reserved_request_params({"a": 1, "b": 2}, {"a", "b"})
        assert allowed == {}
        assert reserved == {"a": 1, "b": 2}

    def test_none_params(self) -> None:
        allowed, reserved = split_reserved_request_params(None, {"a"})
        assert allowed == {}
        assert reserved == {}

    def test_empty_params(self) -> None:
        allowed, reserved = split_reserved_request_params({}, {"a"})
        assert allowed == {}
        assert reserved == {}

    def test_frozenset_keys(self) -> None:
        allowed, reserved = split_reserved_request_params(
            {"x": 1, "y": 2}, frozenset({"x"})
        )
        assert allowed == {"y": 2}
        assert reserved == {"x": 1}

    def test_nested_values_cloned(self) -> None:
        original: dict[str, Any] = {"deep": {"nested": True}, "keep": "val"}
        allowed, reserved = split_reserved_request_params(original, {"deep"})
        assert reserved["deep"] == {"nested": True}
        assert reserved["deep"] is not original["deep"]
