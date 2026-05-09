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
    assert downloaded.name == "demo.txt"
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

    async def _fake_download_from_url(
        url: str,
        temp_dir: Path,
        max_size_mb: float,
        task_uuid: str,
    ) -> str:
        target = temp_dir / "demo.txt"
        target.write_bytes(url.encode("utf-8"))
        return str(target)

    monkeypatch.setattr(
        download_file_handler,
        "_download_from_url",
        _fake_download_from_url,
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
    assert downloaded.name == "demo.txt"
    assert downloaded.read_bytes() == b"https://example.com/demo.txt"
