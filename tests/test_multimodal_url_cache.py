from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, cast

import pytest

from Undefined.ai import multimodal as multimodal_module
from Undefined.ai.multimodal import MultimodalAnalyzer
from Undefined.config.models import VisionModelConfig


def _make_analyzer() -> MultimodalAnalyzer:
    return MultimodalAnalyzer(
        requester=cast(Any, object()),
        vision_config=VisionModelConfig(
            api_url="https://example.invalid/v1",
            api_key="dummy",
            model_name="vision-test",
        ),
    )


@pytest.mark.asyncio
async def test_load_media_content_uses_url_cache(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cache_dir = tmp_path / "multimodal_cache"
    monkeypatch.setattr(multimodal_module, "_MEDIA_URL_CACHE_DIR", cache_dir)

    analyzer = _make_analyzer()
    download_calls = 0

    async def _fake_download(_url: str, cache_path: Path) -> None:
        nonlocal download_calls
        download_calls += 1
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_bytes(b"abc")

    monkeypatch.setattr(analyzer, "_download_url_to_cache", _fake_download)

    url = "https://example.com/cat.png?size=large"
    first = await analyzer._load_media_content(url, "image")
    second = await analyzer._load_media_content(url, "image")

    assert first == "data:image/png;base64,YWJj"
    assert second == "data:image/png;base64,YWJj"
    assert download_calls == 1


@pytest.mark.asyncio
async def test_load_media_content_serializes_same_url_download(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cache_dir = tmp_path / "multimodal_cache"
    monkeypatch.setattr(multimodal_module, "_MEDIA_URL_CACHE_DIR", cache_dir)

    analyzer = _make_analyzer()
    download_calls = 0

    async def _fake_download(_url: str, cache_path: Path) -> None:
        nonlocal download_calls
        download_calls += 1
        await asyncio.sleep(0.05)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_bytes(b"xyz")

    monkeypatch.setattr(analyzer, "_download_url_to_cache", _fake_download)

    url = "https://example.com/race.jpg"
    results = await asyncio.gather(
        *[analyzer._load_media_content(url, "image") for _ in range(8)]
    )

    assert set(results) == {"data:image/jpeg;base64,eHl6"}
    assert download_calls == 1


@pytest.mark.asyncio
async def test_cleanup_keeps_tmp_file_for_active_download(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cache_dir = tmp_path / "multimodal_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(multimodal_module, "_MEDIA_URL_CACHE_DIR", cache_dir)
    monkeypatch.setattr(
        multimodal_module, "_MEDIA_URL_CACHE_CLEANUP_INTERVAL_SECONDS", 0.0
    )

    analyzer = _make_analyzer()
    url = "https://example.com/live.png"
    key = analyzer._build_url_cache_key(url)
    tmp_file = cache_dir / f"{key}.png.tmp"
    tmp_file.write_bytes(b"in-progress")

    lock = asyncio.Lock()
    await lock.acquire()
    analyzer._url_cache_locks[key] = lock

    await analyzer._cleanup_url_cache_if_needed()
    assert tmp_file.exists()

    lock.release()
    await analyzer._cleanup_url_cache_if_needed()
    assert not tmp_file.exists()


@pytest.mark.asyncio
async def test_cleanup_handles_oserror_during_mtime_sort(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cache_dir = tmp_path / "multimodal_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(multimodal_module, "_MEDIA_URL_CACHE_DIR", cache_dir)
    monkeypatch.setattr(
        multimodal_module, "_MEDIA_URL_CACHE_CLEANUP_INTERVAL_SECONDS", 0.0
    )
    monkeypatch.setattr(multimodal_module, "_MEDIA_URL_CACHE_TTL_SECONDS", 999999)
    monkeypatch.setattr(multimodal_module, "_MEDIA_URL_CACHE_MAX_FILES", 1)

    keep_a = cache_dir / "a.bin"
    keep_b = cache_dir / "b.bin"
    keep_a.write_bytes(b"a")
    keep_b.write_bytes(b"b")

    analyzer = _make_analyzer()
    original_stat = Path.stat
    stat_calls: dict[str, int] = {}

    def _flaky_stat(self: Path, *args: Any, **kwargs: Any) -> Any:
        name = self.name
        stat_calls[name] = stat_calls.get(name, 0) + 1
        if name == "b.bin" and stat_calls[name] >= 2:
            raise FileNotFoundError("simulated concurrent delete")
        return original_stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", _flaky_stat)

    await analyzer._cleanup_url_cache_if_needed()
    assert keep_a.exists() or keep_b.exists()


@pytest.mark.asyncio
async def test_cleanup_prunes_unused_url_cache_locks(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cache_dir = tmp_path / "multimodal_cache"
    monkeypatch.setattr(multimodal_module, "_MEDIA_URL_CACHE_DIR", cache_dir)
    monkeypatch.setattr(
        multimodal_module, "_MEDIA_URL_CACHE_CLEANUP_INTERVAL_SECONDS", 0.0
    )

    analyzer = _make_analyzer()
    analyzer._url_cache_locks["stale-a"] = asyncio.Lock()
    analyzer._url_cache_locks["stale-b"] = asyncio.Lock()

    await analyzer._cleanup_url_cache_if_needed()
    assert analyzer._url_cache_locks == {}
