from __future__ import annotations

import json

import pytest

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


def test_canonical_share_url_handles_uppercase_http_scheme() -> None:
    assert (
        canonical_share_url("HTTP://www.douyin.com/video/7312345678901234567")
        == "https://www.iesdouyin.com/share/video/7312345678901234567/"
    )
    assert extract_douyin_ids("HTTPS://v.douyin.com/ABC123/") == [
        "HTTPS://v.douyin.com/ABC123/"
    ]


def test_extract_douyin_ids_ignores_digits_inside_other_urls() -> None:
    # 线上实测：bilibili 图文链接里的 19 位动态 ID 曾被当成裸 aweme_id，
    # 于是同一条消息既走图文管线又走抖音管线（多打两次 iesdouyin 请求）
    assert extract_douyin_ids("https://bilibili.com/opus/933099353259638816") == []
    assert extract_douyin_ids("https://www.bilibili.com/opus/933099353259638816") == []
    assert (
        extract_douyin_ids("https://github.com/glotcode/glot/issues/1234567890123456")
        == []
    )


def test_extract_douyin_ids_keeps_urls_and_naked_ids_together() -> None:
    text = (
        "https://www.bilibili.com/video/BV1xx411c7mD "
        "https://v.douyin.com/abc123/ 7312345678901234567"
    )

    assert extract_douyin_ids(text) == [
        "https://v.douyin.com/abc123/",
        "7312345678901234567",
    ]


@pytest.mark.parametrize("scheme", ["https://", ""])
@pytest.mark.parametrize(
    "url",
    [
        "example.com:8080/video/7312345678901234567",
        "example.com?id=7312345678901234567",
        "example.com#7312345678901234567",
        "example.com:8080?id=7312345678901234567",
        "example.com:8080#7312345678901234567",
    ],
)
def test_extract_douyin_ids_excludes_complete_url_spans(scheme: str, url: str) -> None:
    assert extract_douyin_ids(f"{scheme}{url}") == []
    assert extract_douyin_ids(f"{scheme}{url} 7312345678901234568") == [
        "7312345678901234568"
    ]
