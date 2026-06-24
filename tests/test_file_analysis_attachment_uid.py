from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from Undefined.attachments import AttachmentRegistry, scope_from_context
from Undefined.skills.agents.file_analysis_agent.tools.download_file import (
    handler as download_file_handler,
)
from Undefined.skills.agents.file_analysis_agent.tools.analyze_multimodal import (
    handler as analyze_multimodal_handler,
)
from Undefined.utils.io import write_bytes
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
        "write_bytes_fn": write_bytes,
    }


class _FakeAiClient:
    def __init__(self) -> None:
        self.analyze_calls: list[dict[str, str]] = []
        self.saved_history: list[dict[str, str]] = []

    def get_media_history(self, media_key: str) -> list[dict[str, str]]:
        _ = media_key
        return []

    async def analyze_multimodal(
        self,
        media_url: str,
        *,
        media_type: str,
        prompt_extra: str,
    ) -> dict[str, str]:
        self.analyze_calls.append(
            {
                "media_url": media_url,
                "media_type": media_type,
                "prompt_extra": prompt_extra,
            }
        )
        return {"description": "image analyzed"}

    async def save_media_history(
        self,
        media_key: str,
        question: str,
        answer: str,
    ) -> None:
        self.saved_history.append(
            {"media_key": media_key, "question": question, "answer": answer}
        )


def _analysis_context(
    registry: AttachmentRegistry,
    ai_client: _FakeAiClient,
    *,
    user_id: int = 12345,
) -> dict[str, Any]:
    return {
        "attachment_registry": registry,
        "request_type": "private",
        "user_id": user_id,
        "get_scope_from_context": scope_from_context,
        "ai_client": ai_client,
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
        write_bytes_fn: object,
    ) -> str:
        _ = max_size_mb, task_uuid, write_bytes_fn
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


@pytest.mark.asyncio
async def test_analyze_multimodal_supports_internal_attachment_uid(
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
        display_name="demo.jpg",
        source_kind="test",
    )
    ai_client = _FakeAiClient()

    result = await analyze_multimodal_handler.execute(
        {
            "file_path": record.uid,
            "media_type": "image",
            "prompt": "描述图片",
        },
        _analysis_context(registry, ai_client),
    )

    assert result == "描述：image analyzed"
    assert len(ai_client.analyze_calls) == 1
    call = ai_client.analyze_calls[0]
    assert call["media_url"] != record.uid
    assert Path(call["media_url"]).is_file()
    assert Path(call["media_url"]).read_bytes() == b"image bytes"
    assert call["media_type"] == "image"
    assert call["prompt_extra"] == "描述图片"
    assert ai_client.saved_history


@pytest.mark.asyncio
async def test_analyze_multimodal_rejects_attachment_uid_from_other_scope(
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
        display_name="demo.jpg",
        source_kind="test",
    )
    ai_client = _FakeAiClient()

    result = await analyze_multimodal_handler.execute(
        {"file_path": record.uid, "media_type": "image"},
        _analysis_context(registry, ai_client, user_id=99999),
    )

    assert result == f"错误：附件 UID 不存在或无权访问：{record.uid}"
    assert ai_client.analyze_calls == []
