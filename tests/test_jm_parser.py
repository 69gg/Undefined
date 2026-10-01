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


def test_extract_jm_ids_reads_id_query_links() -> None:
    assert extract_jm_ids("https://18comic.vip/?id=350234") == ["350234"]
    assert extract_jm_ids("https://jmcomic.me/album/350234?foo=1&id=350234") == [
        "350234"
    ]


def test_extract_jm_ids_accepts_digit_bounds() -> None:
    assert extract_jm_ids("jm10000") == ["10000"]  # 5 位下界
    assert extract_jm_ids("jm99999999") == ["99999999"]  # 8 位上界


def test_extract_jm_ids_accepts_fullwidth_separators() -> None:
    assert extract_jm_ids("jm：350234") == ["350234"]
    assert extract_jm_ids("JM 350234") == ["350234"]


def test_extract_jm_ids_ignores_url_and_filename_context() -> None:
    # 前缀前是 URL/路径/文件名分隔符时不算车号，避免把外部链接当车号下载
    assert extract_jm_ids("https://t.me/jm1234567") == []
    assert extract_jm_ids("video_jm1234567.mp4") == []
    assert extract_jm_ids("https://example.com/x/jm1234567") == []
    assert extract_jm_ids("看这个 jm1234567") == ["1234567"]


def test_extract_jm_ids_keeps_original_text_order() -> None:
    # 车号在前、链接在后：先出现的必须排在前面（默认只取第一个，顺序错了会下错本）
    assert extract_jm_ids("jm1111111 https://18comic.vip/album/2222222") == [
        "1111111",
        "2222222",
    ]
    assert extract_jm_ids("https://18comic.vip/album/2222222 然后 jm1111111") == [
        "2222222",
        "1111111",
    ]


def test_extract_from_json_message_survives_malformed_segment() -> None:
    segments: list[dict[str, Any]] = [
        {"type": "json", "data": "not-a-dict"},
        {"type": "json", "data": None},
        {"type": "json"},
        {
            "type": "json",
            "data": {
                "data": '{"meta":{"detail_1":{"qqdocurl":"https://18comic.vip/album/3333333"}}}'
            },
        },
    ]

    # 畸形段落不能中断整条消息的检测
    assert extract_from_json_message(segments) == ["3333333"]


def test_extract_from_json_message_skips_broken_json_body() -> None:
    segments = [{"type": "json", "data": {"data": "{not json"}}]

    assert extract_from_json_message(segments) == []
