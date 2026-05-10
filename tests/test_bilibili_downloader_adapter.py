from __future__ import annotations

from pathlib import Path
from types import TracebackType

import pytest

from Undefined.bilibili import downloader
from Undefined.bilibili.models import DownloadResult, VideoInfo, VideoStats


@pytest.mark.asyncio
async def test_get_video_info_uses_internal_api_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called: dict[str, object] = {}

    class _FakeApiClient:
        def __init__(self, *, cookie: str = "", timeout: float = 0) -> None:
            called["cookie"] = cookie
            called["timeout"] = timeout

        def __enter__(self) -> _FakeApiClient:
            return self

        def __exit__(
            self,
            exc_type: type[BaseException] | None,
            exc: BaseException | None,
            traceback: TracebackType | None,
        ) -> None:
            _ = exc_type, exc, traceback

        def get_video_info(self, video: str) -> VideoInfo:
            called["video"] = video
            return VideoInfo(
                bvid=video,
                aid=1,
                title="demo",
                duration=12,
                cover_url="https://img.example/1.jpg",
                up_name="up",
                desc="desc",
                cid=123,
                page_duration=12,
                stats=VideoStats(),
            )

    monkeypatch.setattr(downloader, "BilibiliApiClient", _FakeApiClient)

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
            aid=1,
            title="long",
            duration=999,
            cover_url="",
            up_name="",
            desc="",
            cid=1,
            page_duration=999,
            stats=VideoStats(),
        )

    def _fake_download_video_sync(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("download should not be called when over max_duration")

    monkeypatch.setattr(downloader, "get_video_info", _fake_get_video_info)
    monkeypatch.setattr(downloader, "_download_video_sync", _fake_download_video_sync)

    path, info, qn = await downloader.download_video(
        "BV1xx411c7mD", max_duration=60, cookie="SESSDATA=abc"
    )

    assert path is None
    assert info.title == "long"
    assert qn == 0


@pytest.mark.asyncio
async def test_download_video_uses_internal_download_core(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    prefetch_called = False
    called: dict[str, object] = {}

    async def _fake_get_video_info(
        _bvid: str, cookie: str = "", sessdata: str = ""
    ) -> downloader.VideoInfo:
        nonlocal prefetch_called
        prefetch_called = True
        raise AssertionError("max_duration=0 should not prefetch video info")

    class _FakeApiClient:
        def __init__(self, *, cookie: str = "", timeout: float = 0) -> None:
            called["cookie"] = cookie
            called["timeout"] = timeout

        def __enter__(self) -> _FakeApiClient:
            return self

        def __exit__(
            self,
            exc_type: type[BaseException] | None,
            exc: BaseException | None,
            traceback: TracebackType | None,
        ) -> None:
            _ = exc_type, exc, traceback

    def _fake_download_core(
        api_client: object,
        *,
        bvid: str,
        save_path: Path,
        prefer_quality: int = 80,
        overwrite: bool = True,
    ) -> DownloadResult:
        called["api_client_type"] = type(api_client).__name__
        called["bvid"] = bvid
        called["save_path"] = save_path
        called["prefer_quality"] = prefer_quality
        called["overwrite"] = overwrite
        output = save_path / f"{bvid}.mp4"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"video")
        info = VideoInfo(
            bvid=bvid,
            aid=1,
            title="from-download",
            duration=30,
            cover_url="",
            up_name="up",
            desc="desc",
            cid=2,
            page_duration=30,
            stats=VideoStats(),
        )
        return DownloadResult(
            path=output,
            size_bytes=output.stat().st_size,
            quality=prefer_quality,
            quality_label="720P",
            video_info=info,
        )

    monkeypatch.setattr(downloader, "get_video_info", _fake_get_video_info)
    monkeypatch.setattr(downloader, "BilibiliApiClient", _FakeApiClient)
    monkeypatch.setattr(downloader, "download_video_core", _fake_download_core)

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
    assert prefetch_called is False
    assert called["cookie"] == "SESSDATA=abc"
    assert called["timeout"] == 480.0
    assert called["bvid"] == "BV1xx411c7mD"
    assert called["prefer_quality"] == 64
    assert called["overwrite"] is True
