from __future__ import annotations

import asyncio
from types import TracebackType
from typing import Any

import httpx
import pytest

from Undefined.douyin import client as douyin_client
from Undefined.douyin import downloader
from Undefined.douyin.client import parse_router_data, parse_video_info
from Undefined.douyin.models import DouyinQualityProbe, DouyinVideoInfo


def _router_html() -> str:
    payload = {
        "loaderData": {
            "video_(id)/page": {
                "videoInfoRes": {
                    "item_list": [
                        {
                            "aweme_id": "7312345678901234567",
                            "desc": "测试标题",
                            "author": {"nickname": "测试作者"},
                            "video": {
                                "duration": 123000,
                                "cover": {
                                    "url_list": ["https://img.example/cover.jpg"]
                                },
                                "play_addr": {"uri": "token-123"},
                            },
                        }
                    ]
                }
            }
        }
    }
    return f"<script>window._ROUTER_DATA = {__import__('json').dumps(payload)}</script>"


def _info() -> DouyinVideoInfo:
    return DouyinVideoInfo(
        aweme_id="7312345678901234567",
        title="测试标题",
        author_name="测试作者",
        desc="测试标题",
        cover_url="https://img.example/cover.jpg",
        duration=123,
        share_url="https://www.iesdouyin.com/share/video/7312345678901234567/",
        play_token="token-123",
    )


def test_parse_router_data_and_video_info() -> None:
    router_data = parse_router_data(_router_html())
    info = parse_video_info(
        router_data,
        fallback_aweme_id="7312345678901234567",
        share_url="https://www.iesdouyin.com/share/video/7312345678901234567/",
    )

    assert info.aweme_id == "7312345678901234567"
    assert info.title == "测试标题"
    assert info.author_name == "测试作者"
    assert info.duration == 123
    assert info.play_token == "token-123"


def test_content_length_prefers_range_total_size() -> None:
    headers = httpx.Headers(
        {
            "content-length": "2",
            "content-range": "bytes 0-1/15084949",
        }
    )

    assert downloader._content_length(headers) == 15084949


@pytest.mark.asyncio
async def test_probe_play_url_uses_ranged_get(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    class _Response:
        status_code = 206
        headers = {"content-range": "bytes 0-1/2048"}
        url = "https://cdn.example/video.mp4"

    class _Client:
        def __init__(self, **kwargs: Any) -> None:
            captured["headers"] = kwargs["headers"]

        async def __aenter__(self) -> _Client:
            return self

        async def __aexit__(
            self,
            exc_type: type[BaseException] | None,
            exc: BaseException | None,
            traceback: TracebackType | None,
        ) -> None:
            _ = exc_type, exc, traceback

        async def get(self, url: str) -> _Response:
            captured["url"] = url
            return _Response()

    monkeypatch.setattr(httpx, "AsyncClient", _Client)

    probe = await downloader.probe_play_url(
        "token-123",
        "1080p",
        referer="https://share.example/",
    )

    assert probe is not None
    assert probe.ratio == "1080p"
    assert probe.size_bytes == 2048
    assert captured["headers"]["Range"] == "bytes=0-1"
    assert captured["headers"]["Referer"] == "https://share.example/"
    assert "ratio=1080p" in captured["url"]


@pytest.mark.asyncio
async def test_download_video_skips_when_duration_exceeds_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_get_video_info(
        *_args: object, **_kwargs: object
    ) -> DouyinVideoInfo:
        return _info()

    monkeypatch.setattr(downloader, "get_video_info", _fake_get_video_info)

    path, info, ratio, size = await downloader.download_video(
        "7312345678901234567",
        max_duration=60,
    )

    assert path is None
    assert info.aweme_id == "7312345678901234567"
    assert ratio is None
    assert size is None


@pytest.mark.asyncio
async def test_probe_qualities_probes_concurrently_and_deduplicates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started: list[str] = []
    release = asyncio.Event()

    async def _fake_probe_play_url(
        video_token: str,
        ratio: str,
        *,
        referer: str,
        config: Any | None = None,
    ) -> DouyinQualityProbe | None:
        assert video_token == "token-123"
        assert referer == _info().share_url
        assert config is None
        started.append(ratio)
        if len(started) == 3:
            release.set()
        await release.wait()
        if ratio == "540p":
            return None
        return DouyinQualityProbe(
            ratio=ratio,
            play_url=f"https://cdn.example/{ratio}.mp4",
            size_bytes=2048,
        )

    monkeypatch.setattr(downloader, "probe_play_url", _fake_probe_play_url)

    probes = await asyncio.wait_for(
        downloader.probe_qualities(_info(), ratios=("1080p", "720p", "540p")),
        timeout=1,
    )

    assert started == ["1080p", "720p", "540p"]
    assert [probe.ratio for probe in probes] == ["1080p"]


@pytest.mark.asyncio
async def test_download_video_oversize_reports_largest_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_get_video_info(
        *_args: object, **_kwargs: object
    ) -> DouyinVideoInfo:
        return _info()

    async def _fake_probe_qualities(
        *_args: object, **_kwargs: object
    ) -> list[DouyinQualityProbe]:
        return [
            DouyinQualityProbe(
                ratio="720p",
                play_url="https://cdn.example/720.mp4",
                size_bytes=2 * 1024 * 1024,
            ),
            DouyinQualityProbe(
                ratio="1080p",
                play_url="https://cdn.example/1080.mp4",
                size_bytes=5 * 1024 * 1024,
            ),
        ]

    monkeypatch.setattr(downloader, "get_video_info", _fake_get_video_info)
    monkeypatch.setattr(downloader, "probe_qualities", _fake_probe_qualities)

    path, info, ratio, size = await downloader.download_video(
        "7312345678901234567",
        max_file_size=1,
    )

    assert path is None
    assert info.aweme_id == "7312345678901234567"
    assert ratio == "1080p"
    assert size == 5 * 1024 * 1024


@pytest.mark.asyncio
async def test_get_anonymous_ttid_parses_nested_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    douyin_client._TTID_CACHE = None

    class _Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return {"data": {"ttid": "anonymous-ttid"}}

    class _Client:
        def __init__(self, **_kwargs: Any) -> None:
            return None

        async def __aenter__(self) -> _Client:
            return self

        async def __aexit__(
            self,
            exc_type: type[BaseException] | None,
            exc: BaseException | None,
            traceback: TracebackType | None,
        ) -> None:
            _ = exc_type, exc, traceback

        async def post(self, _url: str, *, json: dict[str, Any]) -> _Response:
            assert json == {}
            return _Response()

    monkeypatch.setattr(httpx, "AsyncClient", _Client)

    assert await douyin_client.get_anonymous_ttid() == "anonymous-ttid"


@pytest.mark.asyncio
async def test_get_video_info_refreshes_stale_cached_ttid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(douyin_client, "_TTID_CACHE", "stale-ttid")
    seen_cookies: list[str] = []

    class _Response:
        def __init__(
            self,
            *,
            status_code: int = 200,
            text: str = "",
            payload: dict[str, Any] | None = None,
        ) -> None:
            self.status_code = status_code
            self.text = text
            self._payload = payload or {}
            self.request = httpx.Request(
                "GET", "https://www.iesdouyin.com/share/video/7312345678901234567/"
            )
            self.url = str(self.request.url)

        def raise_for_status(self) -> None:
            if self.status_code < 400:
                return
            response = httpx.Response(self.status_code, request=self.request)
            raise httpx.HTTPStatusError(
                "stale ttid",
                request=self.request,
                response=response,
            )

        def json(self) -> dict[str, Any]:
            return self._payload

    class _Client:
        def __init__(self, **kwargs: Any) -> None:
            self.headers = kwargs.get("headers", {})

        async def __aenter__(self) -> _Client:
            return self

        async def __aexit__(
            self,
            exc_type: type[BaseException] | None,
            exc: BaseException | None,
            traceback: TracebackType | None,
        ) -> None:
            _ = exc_type, exc, traceback

        async def post(self, _url: str, *, json: dict[str, Any]) -> _Response:
            assert json == {}
            return _Response(payload={"data": {"ttid": "fresh-ttid"}})

        async def get(self, _url: str) -> _Response:
            cookie = str(self.headers.get("Cookie", ""))
            seen_cookies.append(cookie)
            if "stale-ttid" in cookie:
                return _Response(status_code=403)
            if "fresh-ttid" in cookie:
                return _Response(text=_router_html())
            raise AssertionError(f"unexpected cookie: {cookie}")

    monkeypatch.setattr(httpx, "AsyncClient", _Client)

    info = await douyin_client.get_video_info("7312345678901234567")

    assert info.aweme_id == "7312345678901234567"
    assert seen_cookies == [
        "ttwid=stale-ttid; ttid=stale-ttid",
        "ttwid=fresh-ttid; ttid=fresh-ttid",
    ]
    assert douyin_client._TTID_CACHE == "fresh-ttid"
