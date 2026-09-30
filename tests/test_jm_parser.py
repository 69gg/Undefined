from __future__ import annotations

import json
from typing import Any

from Undefined.jm.parser import (
    extract_from_json_message,
    extract_jm_ids,
    normalize_jm_id,
)


def test_normalize_jm_id_accepts_book_id_forms() -> None:
    assert normalize_jm_id("1114751") == "1114751"
    assert normalize_jm_id(1114751) == "1114751"
    assert normalize_jm_id("JM1114751") == "1114751"
    assert normalize_jm_id("jm1114751") == "1114751"
    assert normalize_jm_id("https://18comic.vip/album/1114751") == "1114751"
    assert normalize_jm_id("https://jmcomic.me/photo/1114751?x=1") == "1114751"


def test_normalize_jm_id_rejects_out_of_range_and_garbage() -> None:
    assert normalize_jm_id("1234") is None
    assert normalize_jm_id("123456789") is None
    assert normalize_jm_id("") is None
    assert normalize_jm_id("JM") is None
    assert normalize_jm_id("https://example.com/album/1114751") is None


def test_extract_jm_ids_accepts_token_forms() -> None:
    assert extract_jm_ids("jm1234567") == ["1234567"]
    assert extract_jm_ids("看看 JM 1114751 吧") == ["1114751"]
    assert extract_jm_ids("jm:1234567") == ["1234567"]
    assert extract_jm_ids("jm#1234567") == ["1234567"]
    assert extract_jm_ids("jm-123456") == ["123456"]
    assert extract_jm_ids("JM1114751 和 jm 1114751") == ["1114751"]


def test_extract_jm_ids_respects_digit_bounds() -> None:
    # 4 位过短、9 位过长，都不算车号；长数字串也不会被截断成 8 位
    assert extract_jm_ids("jm1234") == []
    assert extract_jm_ids("jm123456789") == []
    assert extract_jm_ids("jm00001234567") == []


def test_extract_jm_ids_requires_prefix_boundary() -> None:
    assert extract_jm_ids("xxjm1234567") == []
    assert extract_jm_ids("ajm1234567") == []


def test_extract_jm_ids_does_not_match_bare_numbers() -> None:
    assert extract_jm_ids("1114751 是群号") == []
    assert extract_jm_ids("2024-01-01 12:00:00") == []


def test_extract_jm_ids_accepts_jm_links_only() -> None:
    text = (
        "https://18comic.vip/album/1114751 "
        "https://jmcomic.me/photo/2222222?x=1 "
        "https://example.com/album/3333333"
    )
    assert extract_jm_ids(text) == ["1114751", "2222222"]


def test_extract_jm_ids_strips_url_wrappers() -> None:
    assert extract_jm_ids("看这个（https://18comic.vip/album/1114751）。") == [
        "1114751"
    ]


def test_extract_from_json_message_reads_share_card() -> None:
    payload = {"meta": {"detail_1": {"qqdocurl": "https://18comic.vip/album/1114751"}}}
    segments: list[dict[str, Any]] = [
        {"type": "text", "data": {"text": "jm2222222"}},
        {"type": "json", "data": {"data": json.dumps(payload)}},
    ]

    assert extract_from_json_message(segments) == ["1114751"]


def test_extract_from_json_message_tolerates_broken_payload() -> None:
    segments: list[dict[str, Any]] = [{"type": "json", "data": {"data": "{not-json"}}]
    assert extract_from_json_message(segments) == []
