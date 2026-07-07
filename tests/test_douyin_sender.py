from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

import Undefined.douyin.sender as douyin_sender
from Undefined.attachments import AttachmentRegistry
from Undefined.douyin.models import DouyinVideoInfo


def _video_info() -> DouyinVideoInfo:
    return DouyinVideoInfo(
        aweme_id="7312345678901234567",
        title="测试抖音",
        author_name="测试作者",
        desc="测试简介",
        cover_url="",
        duration=66,
        share_url="https://www.iesdouyin.com/share/video/7312345678901234567/",
        play_token="token-123",
    )


@pytest.mark.asyncio
async def test_send_douyin_video_records_two_node_forward(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    video_path = tmp_path / "douyin.mp4"
    video_path.write_bytes(b"video")
    sender: Any = SimpleNamespace(
        send_group_forward_message=AsyncMock(),
        send_private_forward_message=AsyncMock(),
    )

    monkeypatch.setattr(
        douyin_sender,
        "download_video",
        AsyncMock(return_value=(video_path, _video_info(), "1080p", 5)),
    )
    cleanup_mock = MagicMock()
    monkeypatch.setattr(douyin_sender, "cleanup_path", cleanup_mock)

    result = await douyin_sender.send_douyin_video(
        video_id="7312345678901234567",
        sender=sender,
        target_type="group",
        target_id=123456,
        max_file_size=100,
    )

    assert "已发送抖音合并转发" in result
    sender.send_group_forward_message.assert_awaited_once()
    call = sender.send_group_forward_message.await_args
    assert call is not None
    nodes = call.args[1]
    assert len(nodes) == 2
    assert "测试作者" in nodes[0]["data"]["content"][0]["data"]["text"]
    assert nodes[1]["data"]["content"][0]["type"] == "video"
    assert nodes[1]["data"]["content"][0]["data"]["file"].startswith("file://")
    history_message = call.kwargs["history_message"]
    assert history_message.startswith("[Douyin] 「测试抖音」")
    assert "清晰度: 1080p" in history_message
    cleanup_mock.assert_called_once_with(video_path)


@pytest.mark.asyncio
async def test_fetch_douyin_video_attachment_registers_uid(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    video_path = tmp_path / "douyin.mp4"
    video_path.write_bytes(b"video bytes")
    registry = AttachmentRegistry(
        registry_path=tmp_path / "attachment_registry.json",
        cache_dir=tmp_path / "attachments",
    )

    monkeypatch.setattr(
        douyin_sender,
        "download_video",
        AsyncMock(return_value=(video_path, _video_info(), "720p", 11)),
    )
    cleanup_mock = MagicMock()
    monkeypatch.setattr(douyin_sender, "cleanup_path", cleanup_mock)

    result = await douyin_sender.fetch_douyin_video_attachment(
        "7312345678901234567",
        attachment_registry=registry,
        scope_key="group:123456",
        max_file_size=100,
    )

    assert "测试抖音" in result
    assert '<attachment uid="file_' in result
    uid = result.split('<attachment uid="', 1)[1].split('"', 1)[0]
    record = registry.resolve(uid, "group:123456")
    assert record is not None
    assert record.display_name == "douyin.mp4"
    assert Path(record.local_path or "").read_bytes() == b"video bytes"
    cleanup_mock.assert_called_once_with(video_path)
