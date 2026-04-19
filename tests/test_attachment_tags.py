"""Tests for unified <attachment> / <pic> tag rendering."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from Undefined.attachments import (
    AttachmentRegistry,
    AttachmentRenderError,
    RenderedRichMessage,
    dispatch_pending_file_sends,
    render_message_with_attachments,
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

_PDF_BYTES = b"%PDF-1.4 fake content for testing"


def _make_registry(tmp_path: Path) -> AttachmentRegistry:
    return AttachmentRegistry(
        registry_path=tmp_path / "reg.json",
        cache_dir=tmp_path / "cache",
    )


# ---------- backward compatibility ----------


@pytest.mark.asyncio
async def test_pic_tag_still_works(tmp_path: Path) -> None:
    """<pic uid="..."/> backward compat: renders image as CQ."""
    reg = _make_registry(tmp_path)
    rec = await reg.register_bytes(
        "group:1", _PNG_BYTES, kind="image", display_name="cat.png", source_kind="test"
    )
    msg = f'Look: <pic uid="{rec.uid}"/>'
    result = await render_message_with_attachments(
        msg, registry=reg, scope_key="group:1", strict=False
    )
    assert "[CQ:image" in result.delivery_text
    assert rec.uid in result.history_text
    assert len(result.attachments) == 1
    assert result.pending_file_sends == ()


@pytest.mark.asyncio
async def test_alias_is_same_function() -> None:
    """render_message_with_pic_placeholders is an alias."""
    assert render_message_with_pic_placeholders is render_message_with_attachments


# ---------- unified <attachment> tag ----------


@pytest.mark.asyncio
async def test_attachment_tag_image(tmp_path: Path) -> None:
    """<attachment uid="pic_xxx"/> renders as CQ image (same as <pic>)."""
    reg = _make_registry(tmp_path)
    rec = await reg.register_bytes(
        "group:1", _PNG_BYTES, kind="image", display_name="cat.png", source_kind="test"
    )
    msg = f'Here: <attachment uid="{rec.uid}"/>'
    result = await render_message_with_attachments(
        msg, registry=reg, scope_key="group:1", strict=False
    )
    assert "[CQ:image" in result.delivery_text
    assert rec.uid in result.history_text
    assert result.pending_file_sends == ()


@pytest.mark.asyncio
async def test_attachment_tag_file(tmp_path: Path) -> None:
    """<attachment uid="file_xxx"/> collects into pending_file_sends."""
    reg = _make_registry(tmp_path)
    rec = await reg.register_bytes(
        "group:1", _PDF_BYTES, kind="file", display_name="doc.pdf", source_kind="test"
    )
    msg = f'See doc: <attachment uid="{rec.uid}"/>'
    result = await render_message_with_attachments(
        msg, registry=reg, scope_key="group:1", strict=False
    )
    # File tag removed from delivery text
    assert rec.uid not in result.delivery_text
    assert "See doc: " in result.delivery_text
    # Readable placeholder in history
    assert f"[文件 uid={rec.uid}" in result.history_text
    assert "doc.pdf" in result.history_text
    # Collected in pending
    assert len(result.pending_file_sends) == 1
    assert result.pending_file_sends[0].uid == rec.uid


@pytest.mark.asyncio
async def test_mixed_pic_and_attachment_tags(tmp_path: Path) -> None:
    """Mix of <pic> and <attachment> tags in the same message."""
    reg = _make_registry(tmp_path)
    img = await reg.register_bytes(
        "group:1", _PNG_BYTES, kind="image", display_name="img.png", source_kind="test"
    )
    doc = await reg.register_bytes(
        "group:1", _PDF_BYTES, kind="file", display_name="doc.pdf", source_kind="test"
    )
    msg = f'<pic uid="{img.uid}"/> and <attachment uid="{doc.uid}"/>'
    result = await render_message_with_attachments(
        msg, registry=reg, scope_key="group:1", strict=False
    )
    assert "[CQ:image" in result.delivery_text
    assert len(result.pending_file_sends) == 1
    assert len(result.attachments) == 2


@pytest.mark.asyncio
async def test_pic_tag_rejects_non_image(tmp_path: Path) -> None:
    """<pic> tag with file UID shows type error."""
    reg = _make_registry(tmp_path)
    rec = await reg.register_bytes(
        "group:1", _PDF_BYTES, kind="file", display_name="doc.pdf", source_kind="test"
    )
    msg = f'<pic uid="{rec.uid}"/>'
    result = await render_message_with_attachments(
        msg, registry=reg, scope_key="group:1", strict=False
    )
    assert "类型错误" in result.delivery_text


@pytest.mark.asyncio
async def test_pic_tag_rejects_non_image_strict(tmp_path: Path) -> None:
    """<pic> tag with file UID raises in strict mode."""
    reg = _make_registry(tmp_path)
    rec = await reg.register_bytes(
        "group:1", _PDF_BYTES, kind="file", display_name="doc.pdf", source_kind="test"
    )
    msg = f'<pic uid="{rec.uid}"/>'
    with pytest.raises(AttachmentRenderError, match="不是图片"):
        await render_message_with_attachments(
            msg, registry=reg, scope_key="group:1", strict=True
        )


@pytest.mark.asyncio
async def test_attachment_tag_allows_any_type(tmp_path: Path) -> None:
    """<attachment> tag does NOT reject file UIDs (unlike <pic>)."""
    reg = _make_registry(tmp_path)
    rec = await reg.register_bytes(
        "group:1", _PDF_BYTES, kind="file", display_name="doc.pdf", source_kind="test"
    )
    msg = f'<attachment uid="{rec.uid}"/>'
    result = await render_message_with_attachments(
        msg, registry=reg, scope_key="group:1", strict=True
    )
    assert "类型错误" not in result.delivery_text
    assert len(result.pending_file_sends) == 1


@pytest.mark.asyncio
async def test_invalid_uid_non_strict(tmp_path: Path) -> None:
    """Unknown UID → placeholder in non-strict mode."""
    reg = _make_registry(tmp_path)
    msg = '<attachment uid="pic_nonexist"/>'
    result = await render_message_with_attachments(
        msg, registry=reg, scope_key="group:1", strict=False
    )
    assert "不可用" in result.delivery_text


@pytest.mark.asyncio
async def test_invalid_uid_strict(tmp_path: Path) -> None:
    """Unknown UID → exception in strict mode."""
    reg = _make_registry(tmp_path)
    msg = '<attachment uid="pic_nonexist"/>'
    with pytest.raises(AttachmentRenderError, match="不可用"):
        await render_message_with_attachments(
            msg, registry=reg, scope_key="group:1", strict=True
        )


@pytest.mark.asyncio
async def test_file_tag_missing_local_path(tmp_path: Path) -> None:
    """File with deleted local_path → error placeholder."""
    reg = _make_registry(tmp_path)
    rec = await reg.register_bytes(
        "group:1", _PDF_BYTES, kind="file", display_name="doc.pdf", source_kind="test"
    )
    assert rec.local_path is not None
    Path(rec.local_path).unlink()

    msg = f'<attachment uid="{rec.uid}"/>'
    result = await render_message_with_attachments(
        msg, registry=reg, scope_key="group:1", strict=False
    )
    assert "缺少本地文件" in result.delivery_text
    assert len(result.pending_file_sends) == 0


@pytest.mark.asyncio
async def test_no_tags_passthrough() -> None:
    """Message without tags passes through unchanged."""
    result = await render_message_with_attachments(
        "Hello world", registry=None, scope_key="group:1", strict=False
    )
    assert result.delivery_text == "Hello world"
    assert result.history_text == "Hello world"
    assert result.attachments == []
    assert result.pending_file_sends == ()


@pytest.mark.asyncio
async def test_rendered_rich_message_default_pending() -> None:
    """RenderedRichMessage.pending_file_sends defaults to empty tuple."""
    msg = RenderedRichMessage(delivery_text="hi", history_text="hi", attachments=[])
    assert msg.pending_file_sends == ()


# ---------- dispatch_pending_file_sends ----------


@pytest.mark.asyncio
async def test_dispatch_pending_file_sends_group(tmp_path: Path) -> None:
    """dispatch_pending_file_sends calls sender.send_group_file for group targets."""
    reg = _make_registry(tmp_path)
    rec = await reg.register_bytes(
        "group:1", _PDF_BYTES, kind="file", display_name="doc.pdf", source_kind="test"
    )
    rendered = RenderedRichMessage(
        delivery_text="text",
        history_text="text",
        attachments=[],
        pending_file_sends=(rec,),
    )

    calls: list[tuple[Any, ...]] = []

    class FakeSender:
        async def send_group_file(
            self, group_id: int, file_path: str, name: str | None = None
        ) -> None:
            calls.append(("group", group_id, file_path, name))

        async def send_private_file(
            self, user_id: int, file_path: str, name: str | None = None
        ) -> None:
            calls.append(("private", user_id, file_path, name))

    await dispatch_pending_file_sends(
        rendered, sender=FakeSender(), target_type="group", target_id=12345
    )
    assert len(calls) == 1
    assert calls[0][0] == "group"
    assert calls[0][1] == 12345


@pytest.mark.asyncio
async def test_dispatch_pending_file_sends_private(tmp_path: Path) -> None:
    """dispatch_pending_file_sends calls sender.send_private_file for private targets."""
    reg = _make_registry(tmp_path)
    rec = await reg.register_bytes(
        "group:1",
        _PDF_BYTES,
        kind="file",
        display_name="report.pdf",
        source_kind="test",
    )
    rendered = RenderedRichMessage(
        delivery_text="text",
        history_text="text",
        attachments=[],
        pending_file_sends=(rec,),
    )

    calls: list[tuple[Any, ...]] = []

    class FakeSender:
        async def send_group_file(self, *a: Any, **kw: Any) -> None:
            calls.append(("group", *a))

        async def send_private_file(self, *a: Any, **kw: Any) -> None:
            calls.append(("private", *a))

    await dispatch_pending_file_sends(
        rendered, sender=FakeSender(), target_type="private", target_id=99999
    )
    assert len(calls) == 1
    assert calls[0][0] == "private"
    assert calls[0][1] == 99999


@pytest.mark.asyncio
async def test_dispatch_best_effort_on_failure(tmp_path: Path) -> None:
    """File send failure doesn't propagate — best-effort."""
    reg = _make_registry(tmp_path)
    rec = await reg.register_bytes(
        "group:1", _PDF_BYTES, kind="file", display_name="doc.pdf", source_kind="test"
    )
    rendered = RenderedRichMessage(
        delivery_text="text",
        history_text="text",
        attachments=[],
        pending_file_sends=(rec,),
    )

    class FailingSender:
        async def send_group_file(self, *a: Any, **kw: Any) -> None:
            raise RuntimeError("network error")

        async def send_private_file(self, *a: Any, **kw: Any) -> None:
            raise RuntimeError("network error")

    # Should not raise
    await dispatch_pending_file_sends(
        rendered, sender=FailingSender(), target_type="group", target_id=1
    )


@pytest.mark.asyncio
async def test_dispatch_no_pending_is_noop() -> None:
    """No pending files → no calls."""
    rendered = RenderedRichMessage(
        delivery_text="text", history_text="text", attachments=[]
    )
    await dispatch_pending_file_sends(
        rendered, sender=None, target_type="group", target_id=1
    )
