from __future__ import annotations

from pathlib import Path
from typing import Any

from Undefined.bilibili import download_core
from Undefined.bilibili.models import VideoInfo


class _FakeResponse:
    def __init__(self, content: bytes) -> None:
        self._content = content

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def raise_for_status(self) -> None:
        return None

    def iter_bytes(self, chunk_size: int) -> list[bytes]:
        _ = chunk_size
        return [self._content]


class _FakeHttpClient:
    def stream(self, method: str, url: str) -> _FakeResponse:
        _ = method
        return _FakeResponse(f"stream:{url}".encode())


class _FakeApiClient:
    http_client = _FakeHttpClient()

    def get_video_info(self, bvid: str) -> VideoInfo:
        return VideoInfo(
            bvid=bvid,
            title="bad/name: demo",
            duration=30,
            cover_url="",
            up_name="up",
            desc="desc",
            cid=123,
        )

    def get_playurl(self, bvid: str, cid: int) -> dict[str, Any]:
        _ = bvid, cid
        return {
            "dash": {
                "video": [
                    {"id": 80, "bandwidth": 200, "baseUrl": "video-80-low"},
                    {"id": 80, "bandwidth": 300, "baseUrl": "video-80-high"},
                    {"id": 64, "bandwidth": 100, "baseUrl": "video-64"},
                ]
            }
        }


def test_download_core_selects_quality_and_writes_video_only_stream(
    tmp_path: Path,
) -> None:
    result = download_core.download_video(
        _FakeApiClient(),
        bvid="BV1xx411c7mD",
        save_path=tmp_path,
        prefer_quality=80,
    )

    assert result.quality == 80
    assert result.quality_label == "1080P"
    assert result.video_info.title == "bad/name: demo"
    assert result.path.name == "bad_name_ demo-BV1xx411c7mD.mp4"
    assert result.path.read_bytes() == b"stream:video-80-high"
    assert result.size_bytes == len(b"stream:video-80-high")
