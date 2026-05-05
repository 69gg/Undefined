from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import pytest

from Undefined.utils.render_cache import HtmlRenderCache, compute_render_cache_key


@pytest.mark.asyncio
async def test_render_cache_uses_owned_image_copy(tmp_path: Path) -> None:
    cache = await HtmlRenderCache.create(
        tmp_path / "index.json", max_entries=10, max_size_mb=1
    )
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

    cache = await HtmlRenderCache.create(cache_file, max_entries=10, max_size_mb=1)

    assert await cache.get("legacy") is None


@pytest.mark.asyncio
async def test_render_cache_evicts_least_recently_used_when_entries_exceed_limit(
    tmp_path: Path,
) -> None:
    """超出条目数上限时，按 last_accessed_at 淘汰最久未用项。"""
    cache = await HtmlRenderCache.create(
        tmp_path / "index.json",
        max_entries=2,
        max_size_mb=10,
        flush_interval_seconds=0.0,
    )
    output_path = tmp_path / "render.png"

    output_path.write_bytes(b"image-a")
    await cache.put("a", output_path, output_path.stat().st_size)
    await asyncio.sleep(0.01)
    output_path.write_bytes(b"image-b")
    await cache.put("b", output_path, output_path.stat().st_size)
    # 命中 a，刷新它的 last_accessed_at；之后插入 c 时应淘汰 b
    await asyncio.sleep(0.01)
    assert await cache.get("a") is not None
    await asyncio.sleep(0.01)
    output_path.write_bytes(b"image-c")
    await cache.put("c", output_path, output_path.stat().st_size)

    assert await cache.get("a") is not None
    assert await cache.get("c") is not None
    assert await cache.get("b") is None


@pytest.mark.asyncio
async def test_render_cache_evicts_when_total_size_exceeds_budget(
    tmp_path: Path,
) -> None:
    """超出总字节上限时按 LRU 淘汰直到回到预算内。"""
    # max_size_mb=1，但单图允许 600KB；放两张就会超
    cache = await HtmlRenderCache.create(
        tmp_path / "index.json",
        max_entries=10,
        max_size_mb=1,
        flush_interval_seconds=0.0,
    )
    big_blob = b"x" * (600 * 1024)
    output_path = tmp_path / "render.png"

    output_path.write_bytes(big_blob)
    await cache.put("a", output_path, len(big_blob))
    await asyncio.sleep(0.01)
    output_path.write_bytes(big_blob)
    await cache.put("b", output_path, len(big_blob))

    # a 被字节预算淘汰；b 仍在
    assert await cache.get("a") is None
    assert await cache.get("b") is not None


@pytest.mark.asyncio
async def test_render_cache_disabled_short_circuits_without_touching_disk(
    tmp_path: Path,
) -> None:
    cache_file = tmp_path / "index.json"
    cache = await HtmlRenderCache.create(
        cache_file,
        max_entries=10,
        max_size_mb=1,
        enabled=False,
    )
    output_path = tmp_path / "render.png"
    output_path.write_bytes(b"image")

    await cache.put("k", output_path, output_path.stat().st_size)
    assert await cache.get("k") is None
    # 禁用时不应触发元数据落盘
    assert not cache_file.exists()


@pytest.mark.asyncio
async def test_render_cache_persists_metadata_across_reload(tmp_path: Path) -> None:
    cache_file = tmp_path / "index.json"
    cache = await HtmlRenderCache.create(
        cache_file, max_entries=5, max_size_mb=2, flush_interval_seconds=0.0
    )
    output_path = tmp_path / "render.png"
    output_path.write_bytes(b"persisted")

    await cache.put("persisted", output_path, output_path.stat().st_size)
    await cache.close()

    # 模拟进程重启：构造新实例从同一文件加载
    reloaded = await HtmlRenderCache.create(
        cache_file, max_entries=5, max_size_mb=2, flush_interval_seconds=0.0
    )
    cached = await reloaded.get("persisted")

    assert cached is not None
    assert cached.read_bytes() == b"persisted"


@pytest.mark.asyncio
async def test_render_cache_close_force_flushes_pending_metadata(
    tmp_path: Path,
) -> None:
    """节流期内的 dirty 状态在 close 时应强制落盘。"""
    cache_file = tmp_path / "index.json"
    cache = await HtmlRenderCache.create(
        cache_file, max_entries=5, max_size_mb=2, flush_interval_seconds=999.0
    )
    output_path = tmp_path / "render.png"
    output_path.write_bytes(b"flush-me")

    await cache.put("flush-me", output_path, output_path.stat().st_size)
    # 未到 flush_interval；元数据仅保留在内存中。close 必须强刷。
    await cache.close()

    raw = json.loads(cache_file.read_text(encoding="utf-8"))
    assert "flush-me" in raw


@pytest.mark.asyncio
async def test_render_cache_concurrent_put_keeps_metadata_consistent(
    tmp_path: Path,
) -> None:
    """并发 put 不同 key 时元数据条目数与磁盘文件数一致。"""
    cache = await HtmlRenderCache.create(
        tmp_path / "index.json",
        max_entries=20,
        max_size_mb=4,
        flush_interval_seconds=0.0,
    )

    async def _put(idx: int) -> None:
        path = tmp_path / f"src_{idx}.png"
        path.write_bytes(f"img-{idx}".encode())
        await cache.put(f"k{idx}", path, path.stat().st_size)

    await asyncio.gather(*[_put(i) for i in range(10)])

    for i in range(10):
        assert await cache.get(f"k{i}") is not None

    image_dir = tmp_path / "html"
    assert sum(1 for _ in image_dir.iterdir()) == 10


def test_compute_render_cache_key_is_deterministic_and_distinct() -> None:
    a = compute_render_cache_key("<p>x</p>", 1280, None, None)
    a_again = compute_render_cache_key("<p>x</p>", 1280, None, None)
    b = compute_render_cache_key("<p>y</p>", 1280, None, None)
    c = compute_render_cache_key("<p>x</p>", 1024, None, None)

    assert a == a_again
    assert a != b
    assert a != c
