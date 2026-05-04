from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from Undefined.utils.render_cache import HtmlRenderCache


@pytest.mark.asyncio
async def test_render_cache_uses_owned_image_copy(tmp_path: Path) -> None:
    cache = HtmlRenderCache(tmp_path / "index.json", max_entries=10, max_size_mb=1)
    output_path = tmp_path / "render.png"

    output_path.write_bytes(b"image-a")
    await cache.put("key-a", output_path, output_path.stat().st_size)
    cached_a = await cache.get("key-a")

    assert cached_a is not None
    assert cached_a != output_path
    assert cached_a.parent == tmp_path / "html"
    assert cached_a.read_bytes() == b"image-a"

    output_path.write_bytes(b"image-b")
    await cache.put("key-b", output_path, output_path.stat().st_size)
    cached_a_again = await cache.get("key-a")
    cached_b = await cache.get("key-b")

    assert cached_a_again is not None
    assert cached_b is not None
    assert cached_a_again.read_bytes() == b"image-a"
    assert cached_b.read_bytes() == b"image-b"


@pytest.mark.asyncio
async def test_render_cache_ignores_legacy_external_paths(tmp_path: Path) -> None:
    external = tmp_path / "external.png"
    external.write_bytes(b"legacy")
    cache_file = tmp_path / "index.json"
    now = time.time()
    cache_file.write_text(
        json.dumps(
            {
                "legacy": {
                    "path": str(external),
                    "size_bytes": external.stat().st_size,
                    "created_at": now,
                    "last_accessed_at": now,
                }
            }
        ),
        "utf-8",
    )

    cache = HtmlRenderCache(cache_file, max_entries=10, max_size_mb=1)

    assert await cache.get("legacy") is None
