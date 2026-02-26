from __future__ import annotations

from Undefined.cognitive.vector_store import _sanitize_metadata


def test_sanitize_metadata_drops_empty_message_ids_list() -> None:
    metadata = {
        "request_id": "req-1",
        "message_ids": [],
        "end_seq": 1,
    }

    result = _sanitize_metadata(metadata)

    assert result["request_id"] == "req-1"
    assert result["end_seq"] == 1
    assert "message_ids" not in result


def test_sanitize_metadata_keeps_non_empty_message_ids_list() -> None:
    metadata = {
        "message_ids": ["10001", " ", 10002, None],
        "user_id": "42",
    }

    result = _sanitize_metadata(metadata)

    assert result["user_id"] == "42"
    assert result["message_ids"] == ["10001", 10002]
