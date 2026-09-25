from __future__ import annotations

import html
import json
from typing import Any
from unittest.mock import AsyncMock

import pytest

from Undefined.bilibili import opus_parser
from Undefined.bilibili.opus_parser import (
    extract_opus_from_json_message,
    extract_opus_ids_with_shortlinks,
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("https://www.bilibili.com/opus/933099353259638816", ["933099353259638816"]),
        ("https://m.bilibili.com/opus/106514206257210983", ["106514206257210983"]),
        ("看这个 bilibili.com/opus/123456789012345", ["123456789012345"]),
        ("https://t.bilibili.com/718384798557536290", ["718384798557536290"]),
        ("http://t.bilibili.com/718384798557536290", ["718384798557536290"]),
        (
            "两个 https://www.bilibili.com/opus/111111111111111 和 "
            "https://t.bilibili.com/222222222222222",
            ["111111111111111", "222222222222222"],
        ),
        (
            "重复 https://www.bilibili.com/opus/111111111111111 "
            "https://www.bilibili.com/opus/111111111111111",
            ["111111111111111"],
        ),
    ],
)
async def test_extract_opus_ids_from_plain_text(text: str, expected: list[str]) -> None:
    assert await extract_opus_ids_with_shortlinks(text) == expected


@pytest.mark.asyncio
async def test_extract_opus_ids_ignores_video_links_and_bare_numbers() -> None:
    text = "https://www.bilibili.com/video/BV1xx411c7mD 933099353259638816"
    assert await extract_opus_ids_with_shortlinks(text) == []


@pytest.mark.asyncio
async def test_extract_opus_ids_resolves_short_link(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        opus_parser,
        "resolve_short_url",
        AsyncMock(return_value="https://www.bilibili.com/opus/555555555555555"),
    )
    assert await extract_opus_ids_with_shortlinks("https://b23.tv/abcd123") == [
        "555555555555555"
    ]


@pytest.mark.asyncio
async def test_extract_opus_ids_keeps_direct_hits_when_short_link_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(opus_parser, "resolve_short_url", AsyncMock(return_value=None))
    text = "https://b23.tv/abcd123 https://www.bilibili.com/opus/777777777777777"
    assert await extract_opus_ids_with_shortlinks(text) == ["777777777777777"]


def _json_segment(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "json",
        "data": {"data": html.escape(json.dumps(payload, ensure_ascii=False))},
    }


@pytest.mark.asyncio
async def test_extract_opus_from_json_message_detail_1() -> None:
    segments = [
        _json_segment(
            {
                "app": "com.tencent.structmsg",
                "meta": {
                    "detail_1": {
                        "qqdocurl": "https://www.bilibili.com/opus/888888888888888?share_source=qq"
                    }
                },
            }
        )
    ]
    assert await extract_opus_from_json_message(segments) == ["888888888888888"]


@pytest.mark.asyncio
async def test_extract_opus_from_json_message_news() -> None:
    segments = [
        _json_segment(
            {"meta": {"news": {"jumpUrl": "https://t.bilibili.com/999999999999999"}}}
        )
    ]
    assert await extract_opus_from_json_message(segments) == ["999999999999999"]


@pytest.mark.asyncio
async def test_extract_opus_from_json_message_short_link(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        opus_parser,
        "resolve_short_url",
        AsyncMock(return_value="https://www.bilibili.com/opus/121212121212121"),
    )
    segments = [
        _json_segment({"meta": {"detail_1": {"qqdocurl": "https://b23.tv/xyz987"}}})
    ]
    assert await extract_opus_from_json_message(segments) == ["121212121212121"]


@pytest.mark.asyncio
async def test_extract_opus_from_json_message_skips_invalid_payloads() -> None:
    segments: list[dict[str, Any]] = [
        {"type": "text", "data": {"text": "https://www.bilibili.com/opus/1"}},
        {"type": "json", "data": {"data": "not json"}},
        {"type": "json", "data": {"data": '"just a string"'}},
        {"type": "json", "data": {}},
        _json_segment({"meta": {"detail_1": {"qqdocurl": "https://example.com/x"}}}),
    ]
    assert await extract_opus_from_json_message(segments) == []


@pytest.mark.asyncio
async def test_extract_stops_resolving_short_links_at_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """给了发送预算后，命中数量够了就不再解析剩余短链。"""
    resolver = AsyncMock(return_value="https://www.bilibili.com/opus/555555555555555")
    monkeypatch.setattr(opus_parser, "resolve_short_url", resolver)

    text = " ".join(f"https://b23.tv/link{index}" for index in range(6))
    assert await extract_opus_ids_with_shortlinks(text, limit=1) == ["555555555555555"]
    assert resolver.await_count == 1


@pytest.mark.asyncio
async def test_extract_limit_zero_resolves_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolver = AsyncMock(return_value="https://www.bilibili.com/opus/1")
    monkeypatch.setattr(opus_parser, "resolve_short_url", resolver)

    result = await extract_opus_ids_with_shortlinks(
        "https://b23.tv/x https://www.bilibili.com/opus/2", limit=0
    )

    assert result == []
    resolver.assert_not_awaited()


@pytest.mark.asyncio
async def test_extract_limit_skips_links_when_text_already_fills_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolver = AsyncMock(return_value="https://www.bilibili.com/opus/9")
    monkeypatch.setattr(opus_parser, "resolve_short_url", resolver)

    text = "https://www.bilibili.com/opus/1 https://www.bilibili.com/opus/2 https://b23.tv/x"
    assert await extract_opus_ids_with_shortlinks(text, limit=2) == ["1", "2"]
    resolver.assert_not_awaited()


@pytest.mark.asyncio
async def test_extract_without_limit_resolves_all_short_links(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolver = AsyncMock(
        side_effect=[
            "https://www.bilibili.com/opus/11",
            "https://www.bilibili.com/opus/22",
        ]
    )
    monkeypatch.setattr(opus_parser, "resolve_short_url", resolver)

    result = await extract_opus_ids_with_shortlinks("https://b23.tv/a https://b23.tv/b")

    assert result == ["11", "22"]
    assert resolver.await_count == 2


@pytest.mark.asyncio
async def test_extract_orders_direct_ids_by_position(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """两条正则分两趟扫会打乱顺序：t.bilibili.com 写在前面就必须先返回。"""
    monkeypatch.setattr(opus_parser, "resolve_short_url", AsyncMock(return_value=None))

    text = "https://t.bilibili.com/9 然后 https://www.bilibili.com/opus/8"
    assert await extract_opus_ids_with_shortlinks(text) == ["9", "8"]


@pytest.mark.asyncio
async def test_extract_short_link_before_direct_wins_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """短链出现在直链之前时，预算名额应该先给短链。"""
    resolver = AsyncMock(return_value="https://www.bilibili.com/opus/111")
    monkeypatch.setattr(opus_parser, "resolve_short_url", resolver)

    text = "https://b23.tv/A https://www.bilibili.com/opus/222"
    assert await extract_opus_ids_with_shortlinks(text, limit=1) == ["111"]
    assert resolver.await_count == 1


@pytest.mark.asyncio
async def test_extract_direct_before_short_link_wins_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolver = AsyncMock(return_value="https://www.bilibili.com/opus/111")
    monkeypatch.setattr(opus_parser, "resolve_short_url", resolver)

    text = "https://www.bilibili.com/opus/222 https://b23.tv/A"
    assert await extract_opus_ids_with_shortlinks(text, limit=1) == ["222"]
    resolver.assert_not_awaited()


@pytest.mark.asyncio
async def test_extract_json_card_respects_remaining_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """卡片链路也要受剩余预算约束，名额用完不再解析后续卡片短链。"""

    async def _resolve(url: str) -> str:
        return (
            "https://www.bilibili.com/opus/111"
            if url.endswith("one")
            else "https://www.bilibili.com/opus/222"
        )

    resolver = AsyncMock(side_effect=_resolve)
    monkeypatch.setattr(opus_parser, "resolve_short_url", resolver)

    segments = [
        _json_segment({"meta": {"detail_1": {"qqdocurl": "https://b23.tv/one"}}}),
        _json_segment({"meta": {"news": {"jumpUrl": "https://b23.tv/two"}}}),
    ]

    assert await extract_opus_from_json_message(segments, limit=1) == ["111"]
    assert resolver.await_count == 1

    assert await extract_opus_from_json_message(segments) == ["111", "222"]
    assert resolver.await_count == 3


@pytest.mark.asyncio
async def test_extract_json_card_limit_zero_skips_everything(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolver = AsyncMock(return_value="https://www.bilibili.com/opus/111")
    monkeypatch.setattr(opus_parser, "resolve_short_url", resolver)
    segments = [
        _json_segment({"meta": {"detail_1": {"qqdocurl": "https://b23.tv/one"}}})
    ]

    assert await extract_opus_from_json_message(segments, limit=0) == []
    resolver.assert_not_awaited()
