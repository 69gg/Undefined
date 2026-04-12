from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

import pytest

from Undefined.attachments import (
    AttachmentRecord,
    AttachmentRegistry,
    attachment_refs_to_xml,
    register_message_attachments,
    render_message_with_pic_placeholders,
)
from Undefined.utils import io as io_utils


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
    await reloaded.load()
    assert reloaded.resolve(record.uid, "group:10001") is not None
    assert reloaded.resolve(record.uid, "group:10002") is None


@pytest.mark.asyncio
async def test_attachment_registry_load_uses_async_read_json(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    registry_path = tmp_path / "attachment_registry.json"
    cache_dir = tmp_path / "attachments"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached_file = cache_dir / "pic_async123.png"
    cached_file.write_bytes(_PNG_BYTES)
    seen_calls: list[tuple[Path, bool]] = []
    payload = {
        "pic_async123": {
            "uid": "pic_async123",
            "scope_key": "group:10001",
            "kind": "image",
            "media_type": "image",
            "display_name": "cat.png",
            "source_kind": "test",
            "source_ref": "test",
            "local_path": str(cached_file),
            "mime_type": "image/png",
            "sha256": "digest",
            "created_at": "2026-04-02T00:00:00",
        }
    }

    async def _fake_read_json(file_path: str | Path, use_lock: bool = False) -> Any:
        seen_calls.append((Path(file_path), use_lock))
        return payload

    def _unexpected_sync_read_text(_self: Path, *_args: Any, **_kwargs: Any) -> str:
        raise AssertionError(
            "should use async read_json helper instead of Path.read_text"
        )

    monkeypatch.setattr(io_utils, "read_json", _fake_read_json)
    monkeypatch.setattr(Path, "read_text", _unexpected_sync_read_text)

    registry = AttachmentRegistry(registry_path=registry_path, cache_dir=cache_dir)
    assert seen_calls == []
    await registry.load()

    assert seen_calls == [(registry_path, False)]
    assert registry.resolve("pic_async123", "group:10001") is not None


def test_attachment_refs_to_xml_includes_meme_semantic_metadata() -> None:
    xml = attachment_refs_to_xml(
        [
            {
                "uid": "pic_global01",
                "kind": "image",
                "media_type": "image",
                "display_name": "meme.png",
                "source_kind": "meme_library",
                "semantic_kind": "meme",
                "description": "无语猫猫表情包",
            }
        ]
    )

    assert 'source_kind="meme_library"' in xml
    assert 'semantic_kind="meme"' in xml
    assert 'description="无语猫猫表情包"' in xml


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
async def test_register_message_attachments_recurses_into_forward_images(
    tmp_path: Path,
) -> None:
    registry = AttachmentRegistry(
        registry_path=tmp_path / "attachment_registry.json",
        cache_dir=tmp_path / "attachments",
    )
    payload = base64.b64encode(_PNG_BYTES).decode("ascii")

    async def _fake_get_forward(_forward_id: str) -> list[dict[str, object]]:
        return [
            {
                "message": [
                    {"type": "text", "data": {"text": "转发内容"}},
                    {"type": "image", "data": {"file": f"base64://{payload}"}},
                ]
            }
        ]

    result = await register_message_attachments(
        registry=registry,
        segments=[{"type": "forward", "data": {"id": "forward-1"}}],
        scope_key="group:10001",
        get_forward_messages=_fake_get_forward,
    )

    assert result.normalized_text == "[合并转发: forward-1]"
    assert len(result.attachments) == 1
    assert result.attachments[0]["uid"].startswith("pic_")


@pytest.mark.asyncio
async def test_register_message_attachments_preserves_segment_data_for_images(
    tmp_path: Path,
) -> None:
    registry = AttachmentRegistry(
        registry_path=tmp_path / "attachment_registry.json",
        cache_dir=tmp_path / "attachments",
    )
    payload = base64.b64encode(_PNG_BYTES).decode("ascii")

    result = await register_message_attachments(
        registry=registry,
        segments=[
            {
                "type": "image",
                "data": {
                    "file": f"base64://{payload}",
                    "subType": "1",
                },
            }
        ],
        scope_key="group:10001",
    )

    uid = result.attachments[0]["uid"]
    rendered = await render_message_with_pic_placeholders(
        f'<pic uid="{uid}"/>',
        registry=registry,
        scope_key="group:10001",
        strict=True,
    )

    assert "subType=1" in rendered.delivery_text


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


@pytest.mark.asyncio
async def test_render_message_with_pic_placeholders_escapes_segment_data_for_cq(
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
        segment_data={"summary": "a,b]&["},
    )

    rendered = await render_message_with_pic_placeholders(
        f'<pic uid="{record.uid}"/>',
        registry=registry,
        scope_key="group:10001",
        strict=True,
    )

    assert "summary=a&#44;b&#93;&amp;&#91;" in rendered.delivery_text


@pytest.mark.asyncio
async def test_attachment_registry_prunes_old_records_and_files(tmp_path: Path) -> None:
    registry = AttachmentRegistry(
        registry_path=tmp_path / "attachment_registry.json",
        cache_dir=tmp_path / "attachments",
        max_records=1,
    )

    first = await registry.register_bytes(
        "group:10001",
        _PNG_BYTES,
        kind="image",
        display_name="first.png",
        source_kind="test",
    )
    first_path = Path(str(first.local_path))
    second = await registry.register_bytes(
        "group:10001",
        _PNG_BYTES + b"2",
        kind="image",
        display_name="second.png",
        source_kind="test",
    )

    assert registry.resolve(first.uid, "group:10001") is None
    assert registry.resolve(second.uid, "group:10001") is not None
    assert first_path.exists() is False
    cache_files = [
        item for item in (tmp_path / "attachments").iterdir() if item.is_file()
    ]
    assert len(cache_files) == 1
    assert cache_files[0].name.startswith(second.uid)


@pytest.mark.asyncio
async def test_attachment_registry_load_prunes_orphan_cache_files(
    tmp_path: Path,
) -> None:
    cache_dir = tmp_path / "attachments"
    cache_dir.mkdir(parents=True, exist_ok=True)
    orphan = cache_dir / "orphan.png"
    orphan.write_bytes(_PNG_BYTES)

    registry = AttachmentRegistry(
        registry_path=tmp_path / "attachment_registry.json",
        cache_dir=cache_dir,
    )
    await registry.load()

    assert orphan.exists() is False


@pytest.mark.asyncio
async def test_attachment_registry_scope_mismatch_does_not_fallback_to_global(
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
    resolver_calls: list[str] = []

    def _global_resolver(uid: str) -> AttachmentRecord | None:
        resolver_calls.append(uid)
        return AttachmentRecord(
            uid=uid,
            scope_key="",
            kind="image",
            media_type="image",
            display_name="global.png",
            source_kind="meme_library",
            source_ref="global",
            local_path=record.local_path,
            mime_type="image/png",
            sha256="global",
            created_at="2026-04-05T00:00:00",
            segment_data={"subType": "1"},
        )

    registry.set_global_image_resolver(_global_resolver)

    assert registry.resolve(record.uid, "group:10002") is None
    assert resolver_calls == []
