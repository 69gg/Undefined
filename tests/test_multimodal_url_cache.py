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
