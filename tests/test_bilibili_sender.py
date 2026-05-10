from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest

import Undefined.bilibili.sender as bilibili_sender
from Undefined.bilibili.models import DanmakuItem, VideoStats


def _video_info() -> Any:
    return SimpleNamespace(
        title="测试视频",
        up_name="测试 UP",
        desc="视频简介",
        cover_url="",
        bvid="BV1xx411c7mD",
        url="https://www.bilibili.com/video/BV1xx411c7mD",
        duration=120,
        page_duration=120,
        aid=123,
        cid=456,
        stats=VideoStats(view=1000, like=88, coin=9, favorite=10, danmaku=101),
    )


@pytest.mark.asyncio
async def test_send_bilibili_video_records_history_for_video_message(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    video_path = tmp_path / "video.mp4"
    video_path.write_bytes(b"video")
    sender: Any = SimpleNamespace(
        send_group_forward_message=AsyncMock(),
        send_private_forward_message=AsyncMock(),
    )

    monkeypatch.setattr(
        bilibili_sender,
        "normalize_to_bvid",
        AsyncMock(return_value="BV1xx411c7mD"),
    )
    monkeypatch.setattr(
        bilibili_sender,
        "download_video",
        AsyncMock(return_value=(video_path, _video_info(), 80)),
    )
    monkeypatch.setattr(
        bilibili_sender,
        "fetch_danmaku",
        AsyncMock(
            return_value=[
                DanmakuItem(progress_ms=index * 1000, content=f"弹幕{index}")
                for index in range(101)
            ]
        ),
    )
    cleanup_mock = MagicMock()
    monkeypatch.setattr(bilibili_sender, "cleanup_file", cleanup_mock)

    result = await bilibili_sender.send_bilibili_video(
        video_id="BV1xx411c7mD",
        sender=sender,
        onebot=cast(Any, SimpleNamespace()),
        target_type="group",
        target_id=123456,
        max_file_size=100,
    )

    assert "已发送 Bilibili 合并转发" in result
    sender.send_group_forward_message.assert_awaited_once()
    call = sender.send_group_forward_message.await_args
    assert call is not None
    assert call.args[0] == 123456
    nodes = call.args[1]
    assert len(nodes) == 4
    assert "播放 1000" in nodes[0]["data"]["content"][0]["data"]["text"]
    assert nodes[1]["data"]["content"][0]["type"] == "video"
    assert nodes[1]["data"]["content"][0]["data"]["file"].startswith("file://")
    assert nodes[2]["type"] == "node"
    assert nodes[3]["type"] == "node"
    assert len(nodes[2]["data"]["content"]) == 100
    assert len(nodes[3]["data"]["content"]) == 1
    assert nodes[3]["data"]["content"][0]["data"]["text"].endswith("弹幕100")
    history_message = call.kwargs["history_message"]
    assert history_message.startswith("[Bilibili] 「测试视频」")
    assert "BV1xx411c7mD" in history_message
    cleanup_mock.assert_called_once_with(video_path)
