from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from Undefined.attachments import AttachmentRegistry, scope_from_context
from Undefined.skills.agents.file_analysis_agent.tools.download_file import (
    handler as download_file_handler,
)
from Undefined.utils.paths import ensure_dir


def _download_context(
    tmp_path: Path,
    registry: AttachmentRegistry,
) -> dict[str, Any]:
    return {
        "attachment_registry": registry,
        "request_type": "private",
        "user_id": 12345,
        "get_scope_from_context": scope_from_context,
        "download_cache_dir": tmp_path / "downloads",
        "ensure_dir_fn": ensure_dir,
    }


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
        _download_context(tmp_path, registry),
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
        return type(
            "AttachmentLike",
            (),
            {
                "uid": getattr(record, "uid"),
                "kind": getattr(record, "kind"),
                "media_type": getattr(record, "media_type"),
                "display_name": getattr(record, "display_name"),
                "source_ref": getattr(record, "source_ref"),
                "local_path": "",
            },
        )()

    captured_url: dict[str, str] = {}

    async def _fake_download_from_url(
        url: str,
        temp_dir: Path,
        max_size_mb: float,
        task_uuid: str,
    ) -> str:
        _ = max_size_mb, task_uuid
        captured_url["url"] = url
        target = temp_dir / "file_from_source_ref.txt"
        target.write_bytes(b"https://example.com/demo.txt")
        return str(target)

    monkeypatch.setattr(registry, "ensure_local_file", _fake_ensure_local_file)
    monkeypatch.setattr(
        download_file_handler,
        "_download_from_url",
        _fake_download_from_url,
    )

    result = await download_file_handler.execute(
        {"file_source": record.uid},
        _download_context(tmp_path, registry),
    )

    downloaded = Path(result)
    assert downloaded.is_file()
    assert downloaded.name.startswith("file_")
    assert downloaded.suffix == ".txt"
    assert downloaded.read_bytes() == b"https://example.com/demo.txt"
    assert captured_url["url"] == "https://example.com/demo.txt"


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
        _download_context(tmp_path, registry),
    )

    downloaded = Path(result)
    assert downloaded.is_file()
    assert downloaded.name.startswith("image_")
    assert len(downloaded.name) < 64
    assert downloaded.read_bytes() == b"image bytes"
