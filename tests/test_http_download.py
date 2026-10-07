from __future__ import annotations

import gzip
from pathlib import Path
from typing import Any

import httpx
import pytest

from Undefined.utils import http_download


def _mock_download_client(
    monkeypatch: pytest.MonkeyPatch,
    content: bytes,
    *,
    content_encoding: str | None = None,
    content_length: int | None = None,
) -> None:
    client_type = httpx.AsyncClient

    def handle(request: httpx.Request) -> httpx.Response:
        headers: dict[str, str] = {}
        if content_encoding is not None:
            headers["content-encoding"] = content_encoding
        if content_length is not None:
            headers["content-length"] = str(content_length)
        return httpx.Response(
            200,
            headers=headers,
            stream=httpx.ByteStream(b"" if request.method == "HEAD" else content),
        )

    def client(**kwargs: Any) -> httpx.AsyncClient:
        return client_type(**kwargs, transport=httpx.MockTransport(handle))

    monkeypatch.setattr(httpx, "AsyncClient", client)


@pytest.mark.asyncio
@pytest.mark.parametrize("compressed", [False, True])
async def test_download_checks_wire_size_and_writes_decoded_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, compressed: bool
) -> None:
    content = b"%PDF-1.4\n" + b"compressed download\n" * 300
    wire_content = gzip.compress(content) if compressed else content
    _mock_download_client(
        monkeypatch,
        wire_content,
        content_encoding="gzip" if compressed else None,
        content_length=len(wire_content),
    )
    probe = await http_download.probe_remote_file(
        "https://example.test/file.pdf", timeout_seconds=1
    )
    target = tmp_path / "file.pdf"
    path, size = await http_download.download_remote_file(
        probe.final_url,
        target,
        max_file_size_bytes=len(content),
        timeout_seconds=1,
        expected_size=probe.content_length,
        chunk_size=128,
    )
    assert Path(path) == target
    assert size == len(content)
    assert target.read_bytes() == content
    assert not target.with_suffix(".pdf.part").exists()


@pytest.mark.asyncio
async def test_download_limits_decompressed_file_and_preserves_existing_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    content = b"large decoded content" * 1000
    encoded = gzip.compress(content)
    _mock_download_client(
        monkeypatch, encoded, content_encoding="gzip", content_length=len(encoded)
    )
    target = tmp_path / "file.bin"
    target.write_bytes(b"previous file")
    with pytest.raises(ValueError, match="超过大小限制"):
        await http_download.download_remote_file(
            "https://example.test/file.bin",
            target,
            max_file_size_bytes=1024,
            timeout_seconds=1,
            expected_size=len(encoded),
            chunk_size=128,
        )
    assert target.read_bytes() == b"previous file"
    assert not target.with_suffix(".bin.part").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("compressed", [False, True])
@pytest.mark.parametrize("size_delta", [-1, 1])
async def test_download_rejects_wire_size_changes_without_get_content_length(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    compressed: bool,
    size_delta: int,
) -> None:
    content = b"download" * 100
    encoded = gzip.compress(content) if compressed else content
    _mock_download_client(
        monkeypatch, encoded, content_encoding="gzip" if compressed else None
    )
    target = tmp_path / "file.bin"
    with pytest.raises(ValueError, match="预检"):
        await http_download.download_remote_file(
            "https://example.test/file.bin",
            target,
            max_file_size_bytes=4096,
            timeout_seconds=1,
            expected_size=len(encoded) + size_delta,
            chunk_size=128,
        )
    assert not target.exists()
    assert not target.with_suffix(".bin.part").exists()


@pytest.mark.asyncio
async def test_download_rejects_changed_get_content_length(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    encoded = gzip.compress(b"download" * 100)
    _mock_download_client(
        monkeypatch, encoded, content_encoding="gzip", content_length=len(encoded)
    )
    target = tmp_path / "file.bin"
    with pytest.raises(ValueError, match="大小与预检不一致"):
        await http_download.download_remote_file(
            "https://example.test/file.bin",
            target,
            max_file_size_bytes=4096,
            timeout_seconds=1,
            expected_size=len(encoded) + 1,
        )
    assert not target.exists()
    assert not target.with_suffix(".bin.part").exists()
