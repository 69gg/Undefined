from __future__ import annotations

from pathlib import Path

import pytest

from Undefined.attachments import AttachmentRegistry
from Undefined.skills.agents.file_analysis_agent.tools.download_file import (
    handler as download_file_handler,
)


@pytest.mark.asyncio
async def test_download_file_supports_internal_attachment_uid(
    tmp_path: Path,
) -> None:
    registry = AttachmentRegistry(
        registry_path=tmp_path / "attachment_registry.json",
        cache_dir=tmp_path / "attachments",
    )
    record = await registry.register_bytes(
        "private:12345",
        b"hello attachment",
        kind="file",
        display_name="demo.txt",
        source_kind="test",
    )

    result = await download_file_handler.execute(
        {"file_source": record.uid},
        {
            "attachment_registry": registry,
            "request_type": "private",
            "user_id": 12345,
        },
    )

    downloaded = Path(result)
    assert downloaded.is_file()
    assert downloaded.name.startswith("file_")
    assert downloaded.suffix == ".txt"
    assert downloaded.read_bytes() == b"hello attachment"


@pytest.mark.asyncio
async def test_download_file_redownloads_url_backed_attachment_uid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = AttachmentRegistry(
        registry_path=tmp_path / "attachment_registry.json",
        cache_dir=tmp_path / "attachments",
        remote_download_max_bytes=0,
    )
    record = await registry.register_remote_url(
        "private:12345",
        "https://example.com/demo.txt",
        kind="file",
        display_name="demo.txt",
    )

    async def _fake_ensure_local_file(record: object) -> object:
        cached = tmp_path / "downloaded.txt"
        cached.write_bytes(b"https://example.com/demo.txt")
        return type(
            "AttachmentLike",
            (),
            {
                "uid": getattr(record, "uid"),
                "kind": getattr(record, "kind"),
                "media_type": getattr(record, "media_type"),
                "display_name": getattr(record, "display_name"),
                "local_path": str(cached),
            },
        )()

    monkeypatch.setattr(registry, "ensure_local_file", _fake_ensure_local_file)

    result = await download_file_handler.execute(
        {"file_source": record.uid},
        {
            "attachment_registry": registry,
            "request_type": "private",
            "user_id": 12345,
        },
    )

    downloaded = Path(result)
    assert downloaded.is_file()
    assert downloaded.name.startswith("file_")
    assert downloaded.suffix == ".txt"
    assert downloaded.read_bytes() == b"https://example.com/demo.txt"


@pytest.mark.asyncio
async def test_download_file_uses_random_name_for_unsafe_attachment_name(
    tmp_path: Path,
) -> None:
    registry = AttachmentRegistry(
        registry_path=tmp_path / "attachment_registry.json",
        cache_dir=tmp_path / "attachments",
    )
    record = await registry.register_bytes(
        "private:12345",
        b"image bytes",
        kind="image",
        display_name=f"base64://{'a' * 5000}.png",
        source_kind="base64_image",
        source_ref="segment:0",
    )

    result = await download_file_handler.execute(
        {"file_source": record.uid},
        {
            "attachment_registry": registry,
            "request_type": "private",
            "user_id": 12345,
        },
    )

    downloaded = Path(result)
    assert downloaded.is_file()
    assert downloaded.name.startswith("image_")
    assert len(downloaded.name) < 64
    assert downloaded.read_bytes() == b"image bytes"
