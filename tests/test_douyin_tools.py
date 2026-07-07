from __future__ import annotations

from types import SimpleNamespace

import pytest

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
