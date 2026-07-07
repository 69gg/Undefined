from __future__ import annotations

import json

from Undefined.douyin.parser import (
    canonical_share_url,
    extract_douyin_ids,
    extract_from_json_message,
    normalize_aweme_id,
)


def test_extract_douyin_ids_supports_short_long_and_aweme_id() -> None:
    text = (
        "看看 https://v.douyin.com/abc123/ 和 "
        "https://www.douyin.com/video/7312345678901234567 "
        "还有 7312345678901234568"
    )

    assert extract_douyin_ids(text) == [
        "https://v.douyin.com/abc123/",
        "https://www.douyin.com/video/7312345678901234567",
        "7312345678901234568",
    ]


def test_extract_from_json_message_walks_nested_strings() -> None:
    payload = {
        "meta": {
            "news": {
                "jumpUrl": "https://v.douyin.com/jsonabc/",
                "desc": "视频 7312345678901234567",
            }
        }
    }
    segments = [{"type": "json", "data": {"data": json.dumps(payload)}}]

    assert extract_from_json_message(segments) == [
        "https://v.douyin.com/jsonabc/",
        "7312345678901234567",
    ]


def test_canonical_share_url_for_aweme_and_long_link() -> None:
    assert (
        canonical_share_url("7312345678901234567")
        == "https://www.iesdouyin.com/share/video/7312345678901234567/"
    )
    assert (
        canonical_share_url("https://www.douyin.com/video/7312345678901234567?x=1")
        == "https://www.iesdouyin.com/share/video/7312345678901234567/"
    )
    assert normalize_aweme_id("https://www.douyin.com/video/7312345678901234567") == (
        "7312345678901234567"
    )
