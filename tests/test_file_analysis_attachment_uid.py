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
