"""Tests for attachment SHA-256 hash deduplication."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from Undefined.attachments import AttachmentRegistry


_PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR"
    b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00"
    b"\x90wS\xde"
    b"\x00\x00\x00\x0cIDATx\x9cc``\x00\x00\x00\x02\x00\x01"
    b"\x0b\xe7\x02\x9d"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)

# Different content → different hash
_PNG_BYTES_ALT = _PNG_BYTES + b"\x00"


def _make_registry(tmp_path: Path) -> AttachmentRegistry:
    return AttachmentRegistry(
        registry_path=tmp_path / "reg.json",
        cache_dir=tmp_path / "cache",
    )


@pytest.mark.asyncio
async def test_same_hash_same_scope_same_kind_returns_same_uid(
    tmp_path: Path,
) -> None:
    """Identical bytes + scope + kind → dedup returns same record."""
    reg = _make_registry(tmp_path)
    r1 = await reg.register_bytes(
        "group:1", _PNG_BYTES, kind="image", display_name="a.png", source_kind="test"
    )
    r2 = await reg.register_bytes(
        "group:1", _PNG_BYTES, kind="image", display_name="b.png", source_kind="test"
    )
    assert r1.uid == r2.uid
    assert r1.sha256 == r2.sha256


@pytest.mark.asyncio
async def test_different_content_gets_different_uid(tmp_path: Path) -> None:
    """Different bytes → different records even in same scope/kind."""
    reg = _make_registry(tmp_path)
    r1 = await reg.register_bytes(
        "group:1", _PNG_BYTES, kind="image", display_name="a.png", source_kind="test"
    )
    r2 = await reg.register_bytes(
        "group:1",
        _PNG_BYTES_ALT,
        kind="image",
        display_name="b.png",
        source_kind="test",
    )
    assert r1.uid != r2.uid


@pytest.mark.asyncio
async def test_cross_scope_no_dedup(tmp_path: Path) -> None:
    """Same hash but different scope → separate records (scope isolation)."""
    reg = _make_registry(tmp_path)
    r1 = await reg.register_bytes(
        "group:1", _PNG_BYTES, kind="image", display_name="a.png", source_kind="test"
    )
    r2 = await reg.register_bytes(
        "group:2", _PNG_BYTES, kind="image", display_name="a.png", source_kind="test"
    )
    assert r1.uid != r2.uid


@pytest.mark.asyncio
async def test_cross_kind_no_dedup(tmp_path: Path) -> None:
    """Same hash + scope but different kind → separate records."""
    reg = _make_registry(tmp_path)
    r1 = await reg.register_bytes(
        "group:1", _PNG_BYTES, kind="image", display_name="a.png", source_kind="test"
    )
    r2 = await reg.register_bytes(
        "group:1", _PNG_BYTES, kind="file", display_name="a.bin", source_kind="test"
    )
    assert r1.uid != r2.uid
    assert r1.uid.startswith("pic_")
    assert r2.uid.startswith("file_")


@pytest.mark.asyncio
async def test_file_deleted_causes_new_registration(tmp_path: Path) -> None:
    """If the cached file is deleted, a new record is created."""
    reg = _make_registry(tmp_path)
    r1 = await reg.register_bytes(
        "group:1", _PNG_BYTES, kind="image", display_name="a.png", source_kind="test"
    )
    assert r1.local_path is not None
    Path(r1.local_path).unlink()

    r2 = await reg.register_bytes(
        "group:1", _PNG_BYTES, kind="image", display_name="a.png", source_kind="test"
    )
    assert r2.uid != r1.uid
    assert r2.sha256 == r1.sha256


@pytest.mark.asyncio
async def test_concurrent_identical_registrations(tmp_path: Path) -> None:
    """Concurrent registrations with the same content should be safe."""
    reg = _make_registry(tmp_path)

    results = await asyncio.gather(
        *(
            reg.register_bytes(
                "group:1",
                _PNG_BYTES,
                kind="image",
                display_name="pic.png",
                source_kind="test",
            )
            for _ in range(5)
        )
    )
    uids = {r.uid for r in results}
    # All should resolve to the same UID (dedup)
    assert len(uids) == 1


@pytest.mark.asyncio
async def test_register_local_file_deduplicates(tmp_path: Path) -> None:
    """register_local_file delegates to register_bytes, so dedup applies."""
    reg = _make_registry(tmp_path)
    file_path = tmp_path / "input.png"
    file_path.write_bytes(_PNG_BYTES)

    r1 = await reg.register_bytes(
        "group:1", _PNG_BYTES, kind="image", display_name="a.png", source_kind="test"
    )
    r2 = await reg.register_local_file(
        "group:1", file_path, kind="image", display_name="input.png"
    )
    assert r1.uid == r2.uid
