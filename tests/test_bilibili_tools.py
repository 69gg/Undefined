from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from Undefined.bilibili.models import VideoInfo, VideoStats
from Undefined.skills.tools.bilibili_video import handler as bilibili_video


@pytest.mark.asyncio
async def test_bilibili_video_tool_info_mode_returns_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_normalize_to_bvid(video_id: str) -> str | None:
        assert video_id == "https://www.bilibili.com/video/BV1xx411c7mD"
        return "BV1xx411c7mD"

    async def _fake_get_video_info(bvid: str, cookie: str = "") -> VideoInfo:
        assert bvid == "BV1xx411c7mD"
        assert cookie == "SESSDATA=abc"
        return VideoInfo(
            bvid="BV1xx411c7mD",
            aid=123,
            title="B站标题",
            duration=125,
            cover_url="https://example.com/cover.jpg",
            up_name="测试 UP",
            desc="视频简介",
            cid=456,
            page_duration=125,
            stats=VideoStats(
                view=10000,
                danmaku=20,
                reply=30,
                favorite=40,
                coin=50,
                share=60,
                like=70,
            ),
        )

    send_mock = AsyncMock()
    fetch_mock = AsyncMock()
    monkeypatch.setattr(bilibili_video, "normalize_to_bvid", _fake_normalize_to_bvid)
    monkeypatch.setattr(bilibili_video, "get_video_info", _fake_get_video_info)
    monkeypatch.setattr(bilibili_video, "send_bilibili_video", send_mock)
    monkeypatch.setattr(bilibili_video, "fetch_bilibili_video_attachment", fetch_mock)

    result = await bilibili_video.execute(
        {
            "video_id": "https://www.bilibili.com/video/BV1xx411c7mD",
            "output_mode": "info",
        },
        {
            "runtime_config": SimpleNamespace(bilibili_cookie="SESSDATA=abc"),
        },
    )

    assert "B站标题" in result
    assert "BV: BV1xx411c7mD" in result
    assert "AV: av123" in result
    assert "UP主: 测试 UP" in result
    assert "时长: 2:05" in result
    assert "播放 1.0万" in result
    assert "封面: https://example.com/cover.jpg" in result
    send_mock.assert_not_awaited()
    fetch_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_bilibili_video_tool_info_mode_rejects_invalid_identifier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    get_info_mock = AsyncMock()
    monkeypatch.setattr(
        bilibili_video, "normalize_to_bvid", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(bilibili_video, "get_video_info", get_info_mock)

    result = await bilibili_video.execute(
        {"video_id": "not-a-video", "output_mode": "info"},
        {},
    )

    assert result == "无法解析视频标识: not-a-video"
    get_info_mock.assert_not_awaited()
