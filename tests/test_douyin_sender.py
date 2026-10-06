from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

import Undefined.douyin.sender as douyin_sender
from Undefined.attachments import AttachmentRegistry
from Undefined.douyin.models import DouyinVideoInfo
from Undefined.onebot.client import OneBotDeliveryUncertainError
from Undefined.onebot.file_errors import FileTransferError


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
@pytest.mark.parametrize(
    "error",
    [
        OneBotDeliveryUncertainError("send_forward_msg", "timeout"),
        FileTransferError("stream", "prepare failed"),
    ],
)
async def test_send_douyin_video_does_not_fallback_after_delivery_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    error: RuntimeError,
) -> None:
    video_path = tmp_path / "douyin.mp4"
    video_path.write_bytes(b"video")
    send_mock = AsyncMock(side_effect=error)
    sender: Any = SimpleNamespace(send_group_forward_message=send_mock)
    monkeypatch.setattr(
        douyin_sender,
        "download_video",
        AsyncMock(return_value=(video_path, _video_info(), "1080p", 5)),
    )
    cleanup_mock = AsyncMock()
    monkeypatch.setattr(douyin_sender, "cleanup_path", cleanup_mock)
    recover_mock = AsyncMock()
    monkeypatch.setattr(douyin_sender, "get_video_info", recover_mock)

    with pytest.raises(type(error)) as caught:
        await douyin_sender.send_douyin_video(
            _video_info().aweme_id, sender, "group", 123456
        )

    assert caught.value is error
    send_mock.assert_awaited_once()
    recover_mock.assert_not_awaited()
    cleanup_mock.assert_awaited_once_with(video_path)


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
    cleanup_mock = AsyncMock()
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
    cleanup_mock.assert_awaited_once_with(video_path)


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
    cleanup_mock = AsyncMock()
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
    cleanup_mock.assert_awaited_once_with(video_path)
