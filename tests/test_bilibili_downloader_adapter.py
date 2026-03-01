from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from Undefined.bilibili import downloader


@dataclass
class _RawInfo:
    bvid: str
    title: str
    duration: int
    cover_url: str
    up_name: str
    desc: str
    cid: int


@dataclass
class _RawDownloadResult:
    path: Path
    quality: int
    video_info: _RawInfo


@pytest.mark.asyncio
async def test_get_video_info_uses_oh_my_bilibili_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called: dict[str, object] = {}

    def _fake_get_video_info(
        video: str, *, cookie: str = "", timeout: float = 0
    ) -> _RawInfo:
        called["video"] = video
        called["cookie"] = cookie
        called["timeout"] = timeout
        return _RawInfo(
            bvid=video,
            title="demo",
            duration=12,
            cover_url="https://img.example/1.jpg",
            up_name="up",
            desc="desc",
            cid=123,
        )

    def _fake_download(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("download should not be called")

    monkeypatch.setattr(
        downloader,
        "_require_omb",
        lambda: (_fake_get_video_info, _fake_download),
    )

    info = await downloader.get_video_info("BV1xx411c7mD", cookie="SESSDATA=abc")

    assert info.bvid == "BV1xx411c7mD"
    assert info.title == "demo"
    assert info.duration == 12
    assert info.cid == 123
    assert called["video"] == "BV1xx411c7mD"
    assert called["cookie"] == "SESSDATA=abc"
    assert called["timeout"] == 480.0


@pytest.mark.asyncio
async def test_download_video_returns_info_when_duration_exceeds_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_get_video_info(
        _bvid: str, cookie: str = "", sessdata: str = ""
    ) -> downloader.VideoInfo:
        return downloader.VideoInfo(
            bvid="BV1xx411c7mD",
            title="long",
            duration=999,
            cover_url="",
            up_name="",
            desc="",
            cid=1,
        )

    def _fake_get_video_info_sync(*_args: object, **_kwargs: object) -> object:
        raise AssertionError(
            "sync adapter get_video_info should not be called directly"
        )

    def _fake_download(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("download should not be called when over max_duration")

    monkeypatch.setattr(downloader, "get_video_info", _fake_get_video_info)
    monkeypatch.setattr(
        downloader,
        "_require_omb",
        lambda: (_fake_get_video_info_sync, _fake_download),
    )

    path, info, qn = await downloader.download_video(
        "BV1xx411c7mD", max_duration=60, cookie="SESSDATA=abc"
    )

    assert path is None
    assert info.title == "long"
    assert qn == 0


@pytest.mark.asyncio
async def test_download_video_uses_oh_my_bilibili_download(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    async def _fake_get_video_info(
        _bvid: str, cookie: str = "", sessdata: str = ""
    ) -> downloader.VideoInfo:
        return downloader.VideoInfo(
            bvid="BV1xx411c7mD",
            title="short",
            duration=30,
            cover_url="",
            up_name="up",
            desc="desc",
            cid=2,
        )

    def _fake_omb_get_video_info(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("download path should not call sync get_video_info")

    def _fake_download(
        video: str,
        *,
        save_path: Path,
        cookie: str = "",
        prefer_quality: int = 80,
        timeout: float = 0,
        overwrite: bool = True,
    ) -> _RawDownloadResult:
        output = save_path / f"{video}.mp4"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"video")
        return _RawDownloadResult(
            path=output,
            quality=prefer_quality,
            video_info=_RawInfo(
                bvid=video,
                title="from-download",
                duration=30,
                cover_url="",
                up_name="up",
                desc="desc",
                cid=2,
            ),
        )

    monkeypatch.setattr(downloader, "get_video_info", _fake_get_video_info)
    monkeypatch.setattr(
        downloader,
        "_require_omb",
        lambda: (_fake_omb_get_video_info, _fake_download),
    )

    path, info, qn = await downloader.download_video(
        "BV1xx411c7mD",
        cookie="SESSDATA=abc",
        prefer_quality=64,
        output_dir=tmp_path,
    )

    assert path is not None
    assert path.exists()
    assert qn == 64
    assert info.title == "from-download"
