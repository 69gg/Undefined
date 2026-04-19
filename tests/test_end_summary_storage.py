"""EndSummaryStorage 单元测试"""

from __future__ import annotations

from typing import Any


from Undefined.end_summary_storage import (
    EndSummaryLocation,
    EndSummaryStorage,
)


# ---------------------------------------------------------------------------
# make_record
# ---------------------------------------------------------------------------


class TestMakeRecord:
    def test_basic(self) -> None:
        record = EndSummaryStorage.make_record(
            "summary text", "2025-01-01T00:00:00+08:00"
        )
        assert record["summary"] == "summary text"
        assert record["timestamp"] == "2025-01-01T00:00:00+08:00"
        assert "location" not in record

    def test_strips_summary(self) -> None:
        record = EndSummaryStorage.make_record("  spaces  ", "ts")
        assert record["summary"] == "spaces"

    def test_none_timestamp_auto_generates(self) -> None:
        record = EndSummaryStorage.make_record("text", None)
        assert record["timestamp"]  # 非空
        assert "T" in record["timestamp"]  # ISO 格式

    def test_empty_timestamp_auto_generates(self) -> None:
        record = EndSummaryStorage.make_record("text", "   ")
        assert record["timestamp"]
        assert record["timestamp"].strip() != ""

    def test_with_location(self) -> None:
        loc: EndSummaryLocation = {"type": "group", "name": "测试群"}
        record = EndSummaryStorage.make_record("text", "ts", location=loc)
        assert record.get("location") is not None
        assert record["location"]["type"] == "group"
        assert record["location"]["name"] == "测试群"

    def test_with_private_location(self) -> None:
        loc: EndSummaryLocation = {"type": "private", "name": "好友"}
        record = EndSummaryStorage.make_record("text", "ts", location=loc)
        assert record["location"]["type"] == "private"

    def test_location_none_omitted(self) -> None:
        record = EndSummaryStorage.make_record("text", "ts", location=None)
        assert "location" not in record

    def test_invalid_location_type_ignored(self) -> None:
        bad_loc: Any = {"type": "invalid", "name": "x"}
        record = EndSummaryStorage.make_record("text", "ts", location=bad_loc)
        assert "location" not in record

    def test_location_missing_name_ignored(self) -> None:
        bad_loc: Any = {"type": "group"}
        record = EndSummaryStorage.make_record("text", "ts", location=bad_loc)
        assert "location" not in record

    def test_location_empty_name_ignored(self) -> None:
        bad_loc: Any = {"type": "group", "name": "   "}
        record = EndSummaryStorage.make_record("text", "ts", location=bad_loc)
        assert "location" not in record

    def test_location_non_string_name_ignored(self) -> None:
        bad_loc: Any = {"type": "group", "name": 123}
        record = EndSummaryStorage.make_record("text", "ts", location=bad_loc)
        assert "location" not in record

    def test_location_not_dict_ignored(self) -> None:
        bad: Any = "bad"
        record = EndSummaryStorage.make_record("text", "ts", location=bad)
        assert "location" not in record


# ---------------------------------------------------------------------------
# _normalize_records
# ---------------------------------------------------------------------------


class TestNormalizeRecords:
    def _storage(self) -> EndSummaryStorage:
        return EndSummaryStorage()

    def test_none_returns_empty(self) -> None:
        assert self._storage()._normalize_records(None) == []

    def test_non_list_returns_empty(self) -> None:
        assert self._storage()._normalize_records("not a list") == []

    def test_string_items_converted(self) -> None:
        records = self._storage()._normalize_records(["hello", "world"])
        assert len(records) == 2
        assert records[0]["summary"] == "hello"

    def test_empty_string_items_skipped(self) -> None:
        records = self._storage()._normalize_records(["", "  ", "valid"])
        assert len(records) == 1
        assert records[0]["summary"] == "valid"

    def test_dict_items_normalized(self) -> None:
        data: list[dict[str, Any]] = [
            {"summary": "text", "timestamp": "2025-01-01"},
        ]
        records = self._storage()._normalize_records(data)
        assert len(records) == 1
        assert records[0]["summary"] == "text"

    def test_dict_missing_summary_skipped(self) -> None:
        records = self._storage()._normalize_records([{"timestamp": "t"}])
        assert len(records) == 0

    def test_max_records_trimmed(self) -> None:
        data = [f"summary-{i}" for i in range(250)]
        records = self._storage()._normalize_records(data)
        assert len(records) == 200  # MAX_END_SUMMARIES
