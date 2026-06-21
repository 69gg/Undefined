from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest

import Undefined.bilibili.sender as bilibili_sender
from Undefined.attachments import AttachmentRegistry
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
    assert len(nodes) == 3
    assert "播放 1000" in nodes[0]["data"]["content"][0]["data"]["text"]
    assert nodes[1]["data"]["content"][0]["type"] == "video"
    assert nodes[1]["data"]["content"][0]["data"]["file"].startswith("file://")
    danmaku_groups = nodes[2]["data"]["content"]
    assert len(danmaku_groups) == 2
    assert len(danmaku_groups[0]["data"]["content"]) == 100
    assert len(danmaku_groups[1]["data"]["content"]) == 1
    assert danmaku_groups[0]["data"]["content"][0]["data"]["content"].endswith("弹幕0")
    history_message = call.kwargs["history_message"]
    assert history_message.startswith("[Bilibili] 「测试视频」")
    assert "BV1xx411c7mD" in history_message
    cleanup_mock.assert_called_once_with(video_path)


@pytest.mark.asyncio
async def test_fetch_bilibili_video_attachment_registers_uid(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    video_path = tmp_path / "video.mp4"
    video_path.write_bytes(b"video bytes")
    registry = AttachmentRegistry(
        registry_path=tmp_path / "attachment_registry.json",
        cache_dir=tmp_path / "attachments",
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
    cleanup_mock = MagicMock()
    monkeypatch.setattr(bilibili_sender, "cleanup_file", cleanup_mock)

    result = await bilibili_sender.fetch_bilibili_video_attachment(
        "BV1xx411c7mD",
        attachment_registry=registry,
        scope_key="group:123456",
        max_file_size=100,
    )

    assert "测试视频" in result
    assert '<attachment uid="file_' in result
    uid = result.split('<attachment uid="', 1)[1].split('"', 1)[0]
    record = registry.resolve(uid, "group:123456")
    assert record is not None
    assert record.display_name == "video.mp4"
    assert Path(record.local_path or "").read_bytes() == b"video bytes"
    cleanup_mock.assert_called_once_with(video_path)
