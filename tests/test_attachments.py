from __future__ import annotations

import base64
from pathlib import Path

import pytest

from Undefined.attachments import (
    AttachmentRegistry,
    register_message_attachments,
    render_message_with_pic_placeholders,
)


_PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR"
    b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00"
    b"\x90wS\xde"
    b"\x00\x00\x00\x0cIDATx\x9cc``\x00\x00\x00\x02\x00\x01"
    b"\x0b\xe7\x02\x9d"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)


@pytest.mark.asyncio
async def test_attachment_registry_persists_and_respects_scope(
    tmp_path: Path,
) -> None:
    registry_path = tmp_path / "attachment_registry.json"
    cache_dir = tmp_path / "attachments"
    registry = AttachmentRegistry(registry_path=registry_path, cache_dir=cache_dir)

    record = await registry.register_bytes(
        "group:10001",
        _PNG_BYTES,
        kind="image",
        display_name="cat.png",
        source_kind="test",
    )

    reloaded = AttachmentRegistry(registry_path=registry_path, cache_dir=cache_dir)
    assert reloaded.resolve(record.uid, "group:10001") is not None
    assert reloaded.resolve(record.uid, "group:10002") is None


@pytest.mark.asyncio
async def test_register_message_attachments_normalizes_webui_base64_image(
    tmp_path: Path,
) -> None:
    registry = AttachmentRegistry(
        registry_path=tmp_path / "attachment_registry.json",
        cache_dir=tmp_path / "attachments",
    )
    payload = base64.b64encode(_PNG_BYTES).decode("ascii")
    segments = [
        {"type": "text", "data": {"text": "我给你看"}},
        {"type": "image", "data": {"file": f"base64://{payload}"}},
        {"type": "text", "data": {"text": "这张图"}},
    ]

    result = await register_message_attachments(
        registry=registry,
        segments=segments,
        scope_key="webui",
    )

    assert len(result.attachments) == 1
    uid = result.attachments[0]["uid"]
    assert uid.startswith("pic_")
    assert uid in result.normalized_text
    assert "这张图" in result.normalized_text


@pytest.mark.asyncio
async def test_render_message_with_pic_placeholders_uses_file_uri_and_shadow_text(
    tmp_path: Path,
) -> None:
    registry = AttachmentRegistry(
        registry_path=tmp_path / "attachment_registry.json",
        cache_dir=tmp_path / "attachments",
    )
    record = await registry.register_bytes(
        "group:10001",
        _PNG_BYTES,
        kind="image",
        display_name="cat.png",
        source_kind="test",
    )

    rendered = await render_message_with_pic_placeholders(
        f'介绍一下\n<pic uid="{record.uid}"/>\n如图',
        registry=registry,
        scope_key="group:10001",
        strict=True,
    )

    assert "[CQ:image,file=file://" in rendered.delivery_text
    assert f"[图片 uid={record.uid} name=cat.png]" in rendered.history_text
