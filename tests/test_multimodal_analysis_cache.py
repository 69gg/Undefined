from __future__ import annotations

import base64
from pathlib import Path
from typing import Any, cast
from unittest.mock import AsyncMock

from PIL import Image
from PIL.PngImagePlugin import PngInfo
import pytest

from Undefined.ai.multimodal import MultimodalAnalyzer
from Undefined.config.models import VisionModelConfig


def _analyzer(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[MultimodalAnalyzer, AsyncMock]:
    monkeypatch.setattr(MultimodalAnalyzer, "_load_history", lambda self: None)
    requester = AsyncMock()
    requester.request.side_effect = [
        {"choices": [{"message": {"content": "描述：red image"}}]},
        {"choices": [{"message": {"content": "描述：blue image"}}]},
    ]
    return (
        MultimodalAnalyzer(
            requester=cast(Any, requester),
            vision_config=VisionModelConfig(
                api_url="https://example.invalid/v1",
                api_key="test-only",
                model_name="vision-test",
            ),
        ),
        requester,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("source_kind", ["path", "data_url"])
async def test_analysis_cache_distinguishes_complete_media_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, source_kind: str
) -> None:
    directory = tmp_path / ("common-prefix-" * 10)
    directory.mkdir()
    sources: list[str] = []
    metadata = PngInfo()
    metadata.add_text("common-metadata", "same prefix " * 20)
    for color in ["red", "blue"]:
        path = directory / f"{color}.png"
        with Image.new("RGB", (1, 1), color=color) as image:
            image.save(path, pnginfo=metadata)
        sources.append(
            str(path)
            if source_kind == "path"
            else "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode()
        )
    assert sources[0][:100] == sources[1][:100]
    analyzer, requester = _analyzer(monkeypatch)

    first = await analyzer.analyze(sources[0], "image")
    second = await analyzer.analyze(sources[1], "image")
    repeated = await analyzer.analyze(sources[0], "image")

    assert first["description"] == "red image"
    assert second["description"] == "blue image"
    assert repeated == first
    assert requester.request.await_count == 2
    first_content = requester.request.await_args_list[0].kwargs["messages"][0][
        "content"
    ][1]
    second_content = requester.request.await_args_list[1].kwargs["messages"][0][
        "content"
    ][1]
    assert first_content != second_content


@pytest.mark.asyncio
async def test_analysis_cache_distinguishes_extra_instructions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "image.png"
    with Image.new("RGB", (1, 1), color="red") as image:
        image.save(path)
    analyzer, requester = _analyzer(monkeypatch)

    first = await analyzer.analyze(str(path), "image", "describe color")
    second = await analyzer.analyze(str(path), "image", "describe mood")
    repeated = await analyzer.analyze(str(path), "image", "describe color")

    assert first != second
    assert repeated == first
    assert requester.request.await_count == 2
