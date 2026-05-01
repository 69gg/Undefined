from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest

import Undefined.bilibili.sender as bilibili_sender


def _video_info() -> Any:
    return SimpleNamespace(
        title="测试视频",
        up_name="测试 UP",
        desc="视频简介",
        cover_url="",
        bvid="BV1xx411c7mD",
        duration=120,
    )


@pytest.mark.asyncio
async def test_send_bilibili_video_records_history_for_video_message(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    video_path = tmp_path / "video.mp4"
    video_path.write_bytes(b"video")
    sender: Any = SimpleNamespace(
        send_group_message=AsyncMock(),
        send_private_message=AsyncMock(),
        register_sent_file_attachment=AsyncMock(
            return_value=[
                {
                    "uid": "file_video",
                    "kind": "video",
                    "media_type": "video",
                    "display_name": "video.mp4",
                }
            ]
        ),
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

    result = await bilibili_sender.send_bilibili_video(
        video_id="BV1xx411c7mD",
        sender=sender,
        onebot=cast(Any, SimpleNamespace()),
        target_type="group",
        target_id=123456,
        max_file_size=100,
    )

    assert "已发送视频" in result
    sender.register_sent_file_attachment.assert_awaited_once()
    assert sender.send_group_message.await_count == 2
    video_call = sender.send_group_message.await_args_list[1]
    assert video_call.args[1].startswith("[CQ:video,file=file://")
    history_message = video_call.kwargs["history_message"]
    assert history_message.startswith("[视频] 「测试视频」")
    assert "BV1xx411c7mD" in history_message
    assert video_call.kwargs["attachments"][0]["uid"] == "file_video"
    cleanup_mock.assert_called_once_with(video_path)
