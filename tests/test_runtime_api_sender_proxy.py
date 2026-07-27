from __future__ import annotations

from pathlib import Path

import pytest

from Undefined.api._helpers import _WebUIVirtualSender
from Undefined.api.routes.chat import _normalize_webchat_output
from Undefined.attachments import AttachmentRegistry


@pytest.mark.asyncio
async def test_webui_virtual_sender_redirects_private_and_group_messages() -> None:
    captured: list[tuple[int, str]] = []

    async def _capture(user_id: int, message: str) -> None:
        captured.append((user_id, message))

    sender = _WebUIVirtualSender(
        virtual_user_id=42,
        send_private_callback=_capture,
        onebot=object(),
    )

    await sender.send_private_message(123456, "hello private")
    await sender.send_group_message(654321, "hello group")

    assert captured == [
        (42, "hello private"),
        (42, "hello group"),
    ]
    assert sender.onebot is not None


@pytest.mark.asyncio
async def test_webui_virtual_sender_reuses_registered_music_attachment(
    tmp_path: Path,
) -> None:
    registry = AttachmentRegistry(
        registry_path=tmp_path / "registry.json",
        cache_dir=tmp_path / "cache",
    )
    record = await registry.register_bytes(
        "webui",
        b"audio-bytes",
        kind="audio",
        display_name="Test Song - Test Singer.mp3",
        source_kind="lxmusic2api_audio",
        source_ref="lxmusic2api:wy:123",
        mime_type="audio/mpeg",
        segment_data={"resolved_quality": "320k"},
        semantic_kind="music",
        description="[音乐] 名称：Test Song；歌手/作者：Test Singer；音质：320 kbps",
    )
    captured: list[tuple[int, str]] = []

    async def _capture(user_id: int, message: str) -> None:
        captured.append((user_id, message))

    sender = _WebUIVirtualSender(
        virtual_user_id=42,
        send_private_callback=_capture,
    )
    assert record.local_path is not None
    await sender.send_private_file(
        123456,
        record.local_path,
        name=record.display_name,
        history_attachment=record,
    )

    assert captured == [(42, f'<attachment uid="{record.uid}"/>')]
    normalized_text, attachments = await _normalize_webchat_output(
        captured[0][1],
        registry=registry,
        scope_key="webui",
        resolve_image_url=None,
        get_forward_messages=None,
    )

    assert normalized_text == f'<attachment uid="{record.uid}"/>'
    assert attachments == [record.prompt_ref()]
    assert attachments[0]["uid"] == record.uid
    assert attachments[0]["kind"] == "audio"
    assert attachments[0]["semantic_kind"] == "music"
    assert "音质：320 kbps" in attachments[0]["description"]
