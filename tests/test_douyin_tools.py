from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from Undefined.douyin.models import DouyinVideoInfo
from Undefined.skills.tools.douyin_video import handler as douyin_video


@pytest.mark.asyncio
async def test_douyin_video_tool_uses_runtime_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    async def _fake_send_douyin_video(*args: object, **kwargs: object) -> str:
        captured["args"] = args
        captured.update(kwargs)
        return "ok"

    monkeypatch.setattr(douyin_video, "send_douyin_video", _fake_send_douyin_video)

    context = {
        "request_type": "group",
        "group_id": 123456,
        "sender": object(),
        "runtime_config": SimpleNamespace(
            douyin_max_duration=42,
            douyin_max_file_size=99,
            douyin_prefer_ratios=["720p", "360p"],
        ),
    }
    result = await douyin_video.execute({"video_id": "7312345678901234567"}, context)

    assert result == "ok"
    assert captured["video_id"] == "7312345678901234567"
    assert captured["target_type"] == "group"
    assert captured["target_id"] == 123456
    assert captured["max_duration"] == 42
    assert captured["max_file_size"] == 99
    assert captured["prefer_ratios"] == ("720p", "360p")


@pytest.mark.asyncio
async def test_douyin_video_tool_uid_mode_registers_attachment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    async def _fake_fetch_douyin_video_attachment(
        *args: object, **kwargs: object
    ) -> str:
        captured["args"] = args
        captured.update(kwargs)
        return '已获取抖音视频：标题\n视频: <attachment uid="file_douyin"/>'

    monkeypatch.setattr(
        douyin_video,
        "fetch_douyin_video_attachment",
        _fake_fetch_douyin_video_attachment,
    )

    attachment_registry = object()
    runtime_config = SimpleNamespace(
        douyin_max_duration=42,
        douyin_max_file_size=99,
        douyin_prefer_ratios=["720p", "360p"],
    )
    result = await douyin_video.execute(
        {"video_id": "7312345678901234567", "output_mode": "uid"},
        {
            "request_type": "group",
            "group_id": 123456,
            "attachment_registry": attachment_registry,
            "runtime_config": runtime_config,
        },
    )

    assert '<attachment uid="file_douyin"/>' in result
    assert captured["video_id"] == "7312345678901234567"
    assert captured["attachment_registry"] is attachment_registry
    assert captured["scope_key"] == "group:123456"
    assert captured["max_duration"] == 42
    assert captured["max_file_size"] == 99
    assert captured["prefer_ratios"] == ("720p", "360p")
    assert captured["config"] is runtime_config


@pytest.mark.asyncio
async def test_douyin_video_tool_info_mode_returns_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_get_video_info(
        video_id: str,
        *,
        config: object | None = None,
    ) -> DouyinVideoInfo:
        assert video_id == "7312345678901234567"
        assert config is runtime_config
        return DouyinVideoInfo(
            aweme_id="7312345678901234567",
            title="抖音标题",
            author_name="作者",
            desc="抖音简介",
            cover_url="https://example.com/cover.jpg",
            duration=61,
            share_url="https://www.iesdouyin.com/share/video/7312345678901234567/",
            play_token="token",
        )

    runtime_config = SimpleNamespace(douyin_max_duration=42)
    send_mock = AsyncMock()
    fetch_mock = AsyncMock()
    monkeypatch.setattr(douyin_video, "get_video_info", _fake_get_video_info)
    monkeypatch.setattr(douyin_video, "send_douyin_video", send_mock)
    monkeypatch.setattr(douyin_video, "fetch_douyin_video_attachment", fetch_mock)

    result = await douyin_video.execute(
        {"video_id": "7312345678901234567", "output_mode": "info"},
        {"runtime_config": runtime_config},
    )

    assert "抖音标题" in result
    assert "ID: 7312345678901234567" in result
    assert "作者: 作者" in result
    assert "时长: 1:01" in result
    assert "封面: https://example.com/cover.jpg" in result
    send_mock.assert_not_awaited()
    fetch_mock.assert_not_awaited()
