from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from jsonschema import Draft202012Validator

from Undefined.attachments import scope_from_context
from Undefined.skills.toolsets.messages.send_voice.handler import execute
from Undefined.utils import io as async_io
from Undefined.utils.message_targets import resolve_delivery_address


def _context(**values: Any) -> dict[str, Any]:
    return {
        "request_type": "private",
        "user_id": 12345,
        "sender_id": 12345,
        "channel": "wechat",
        "address": "wechat:12345",
        "resolve_delivery_address": resolve_delivery_address,
        "get_scope_from_context": scope_from_context,
        "mark_message_sent_this_turn": lambda context: context.__setitem__(
            "message_sent_this_turn", True
        ),
        **values,
    }


@pytest.mark.asyncio
async def test_send_voice_schema_uses_uid_and_optional_address() -> None:
    source = await async_io.read_text(
        Path("src/Undefined/skills/toolsets/messages/send_voice/config.json")
    )
    assert source is not None
    function = json.loads(source)["function"]
    validator = Draft202012Validator(function["parameters"])

    assert validator.is_valid({"uid": "file_ab12cd34"})
    assert validator.is_valid({"uid": "file_ab12cd34", "address": "wechat:12345"})
    assert not validator.is_valid({"uid": "/srv/private/voice.wav"})
    assert not validator.is_valid({"uid": "file_ab12cd34", "address": "private:12345"})
    assert "普通 <attachment" in function["description"]


@pytest.mark.asyncio
async def test_send_voice_resolves_attachment_and_current_wechat_route() -> None:
    record = SimpleNamespace(
        uid="file_voice",
        media_type="file",
        mime_type="audio/wav",
        display_name="reply.wav",
        local_path="/cache/reply.wav",
    )
    registry = SimpleNamespace(
        resolve_async=AsyncMock(return_value=record),
        ensure_local_file=AsyncMock(return_value=record),
    )
    sender = SimpleNamespace(
        send_address_voice=AsyncMock(return_value="client-voice-1")
    )
    context = _context(attachment_registry=registry, sender=sender)

    result = await execute({"uid": "file_voice"}, context)

    assert result == "语音已发送（message_id=client-voice-1）"
    registry.resolve_async.assert_awaited_once_with("file_voice", "private:12345")
    sender.send_address_voice.assert_awaited_once()
    call = sender.send_address_voice.await_args
    assert call is not None
    assert call.args[0].canonical == "wechat:12345"
    assert call.args[1] == "/cache/reply.wav"
    assert call.kwargs["name"] == "reply.wav"
    assert call.kwargs["history_attachment"] is record
    assert context["message_sent_this_turn"] is True


@pytest.mark.asyncio
async def test_send_voice_accepts_explicit_qq_address() -> None:
    record = SimpleNamespace(
        uid="file_voice",
        media_type="audio",
        mime_type="audio/ogg",
        display_name="reply.ogg",
        local_path="/cache/reply.ogg",
    )
    registry = SimpleNamespace(
        resolve_async=AsyncMock(return_value=record),
        ensure_local_file=AsyncMock(return_value=record),
    )
    sender = SimpleNamespace(send_address_voice=AsyncMock(return_value=123))

    result = await execute(
        {"uid": "file_voice", "address": "qq:54321"},
        _context(attachment_registry=registry, sender=sender),
    )

    assert result == "语音已发送（message_id=123）"
    call = sender.send_address_voice.await_args
    assert call is not None
    assert call.args[0].canonical == "qq:54321"
    assert call.kwargs["history_attachment"] is record


@pytest.mark.asyncio
async def test_send_voice_rejects_non_audio_attachment() -> None:
    record = SimpleNamespace(
        uid="file_doc",
        media_type="file",
        mime_type="application/pdf",
        display_name="document.pdf",
    )
    registry = SimpleNamespace(
        resolve_async=AsyncMock(return_value=record),
        ensure_local_file=AsyncMock(return_value=record),
    )
    sender = SimpleNamespace(send_address_voice=AsyncMock())

    result = await execute(
        {"uid": "file_doc"},
        _context(attachment_registry=registry, sender=sender),
    )

    assert result == "发送失败：该附件不是支持的音频文件"
    registry.ensure_local_file.assert_not_awaited()
    sender.send_address_voice.assert_not_awaited()
