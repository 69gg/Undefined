from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from Undefined.attachments import AttachmentRegistry
from Undefined.skills.toolsets.messages.send_message.handler import execute


def _build_runtime_config() -> Any:
    return SimpleNamespace(
        is_group_allowed=lambda _gid: True,
        is_private_allowed=lambda _uid: True,
    )


@pytest.mark.asyncio
async def test_send_message_private_passes_context_group_as_preferred_temp_group() -> (
    None
):
    sender = SimpleNamespace(
        send_group_message=AsyncMock(),
        send_private_message=AsyncMock(),
    )
    context: dict[str, Any] = {
        "request_type": "group",
        "group_id": 10001,
        "user_id": 20002,
        "sender_id": 20002,
        "request_id": "req-1",
        "runtime_config": _build_runtime_config(),
        "sender": sender,
    }

    result = await execute(
        {
            "target_type": "private",
            "target_id": 30003,
            "message": "hello",
        },
        context,
    )

    assert result == "消息已发送"
    sender.send_private_message.assert_called_once_with(
        30003,
        "hello",
        reply_to=None,
        preferred_temp_group_id=10001,
        history_message="hello",
    )
    sender.send_group_message.assert_not_called()
    assert context["message_sent_this_turn"] is True


@pytest.mark.asyncio
async def test_send_message_group_callback_passes_reply_to() -> None:
    send_message_callback = AsyncMock()
    context: dict[str, Any] = {
        "request_type": "group",
        "group_id": 10001,
        "sender_id": 20002,
        "request_id": "req-2",
        "runtime_config": _build_runtime_config(),
        "send_message_callback": send_message_callback,
    }

    result = await execute(
        {
            "message": "hello group",
            "reply_to": 54321,
        },
        context,
    )

    assert result == "消息已发送"
    send_message_callback.assert_awaited_once_with("hello group", reply_to=54321)
    assert context["message_sent_this_turn"] is True


@pytest.mark.asyncio
async def test_send_message_private_callback_passes_reply_to() -> None:
    send_private_message_callback = AsyncMock()
    context: dict[str, Any] = {
        "request_type": "private",
        "user_id": 30003,
        "sender_id": 30003,
        "request_id": "req-3",
        "runtime_config": _build_runtime_config(),
        "send_private_message_callback": send_private_message_callback,
    }

    result = await execute(
        {
            "message": "hello private",
            "reply_to": 65432,
        },
        context,
    )

    assert result == "消息已发送"
    send_private_message_callback.assert_awaited_once_with(
        30003, "hello private", reply_to=65432
    )
    assert context["message_sent_this_turn"] is True


@pytest.mark.asyncio
async def test_send_message_does_not_implicitly_use_trigger_message_id() -> None:
    sender = SimpleNamespace(
        send_group_message=AsyncMock(),
        send_private_message=AsyncMock(),
    )
    context: dict[str, Any] = {
        "request_type": "group",
        "group_id": 10001,
        "sender_id": 20002,
        "trigger_message_id": 99999,
        "request_id": "req-4",
        "runtime_config": _build_runtime_config(),
        "sender": sender,
    }

    result = await execute(
        {
            "message": "hello without quote",
        },
        context,
    )

    assert result == "消息已发送"
    sender.send_group_message.assert_called_once_with(
        10001,
        "hello without quote",
        reply_to=None,
        history_message="hello without quote",
    )


@pytest.mark.asyncio
async def test_send_message_returns_sent_message_id_when_available() -> None:
    sender = SimpleNamespace(
        send_group_message=AsyncMock(return_value=77777),
        send_private_message=AsyncMock(),
    )
    context: dict[str, Any] = {
        "request_type": "group",
        "group_id": 10001,
        "sender_id": 20002,
        "request_id": "req-5",
        "runtime_config": _build_runtime_config(),
        "sender": sender,
    }

    result = await execute(
        {
            "message": "hello with id",
        },
        context,
    )

    assert result == "消息已发送（message_id=77777）"


@pytest.mark.asyncio
async def test_send_message_renders_pic_uid_before_sending(tmp_path: Path) -> None:
    sender = SimpleNamespace(
        send_group_message=AsyncMock(return_value=77777),
        send_private_message=AsyncMock(),
    )
    registry = AttachmentRegistry(
        registry_path=tmp_path / "attachment_registry.json",
        cache_dir=tmp_path / "attachments",
    )
    record = await registry.register_bytes(
        "group:10001",
        b"\x89PNG\r\n\x1a\n",
        kind="image",
        display_name="demo.png",
        source_kind="test",
    )
    context: dict[str, Any] = {
        "request_type": "group",
        "group_id": 10001,
        "sender_id": 20002,
        "request_id": "req-6",
        "runtime_config": _build_runtime_config(),
        "sender": sender,
        "attachment_registry": registry,
    }

    result = await execute(
        {
            "message": f'图文并茂\n<pic uid="{record.uid}"/>\n结束',
        },
        context,
    )

    assert result == "消息已发送（message_id=77777）"
    sent_args = sender.send_group_message.await_args
    assert "[CQ:image,file=file://" in sent_args.args[1]
    assert sent_args.kwargs["history_message"] == (
        f"图文并茂\n[图片 uid={record.uid} name=demo.png]\n结束"
    )


@pytest.mark.asyncio
async def test_send_message_renders_webui_scoped_pic_uid_before_sending(
    tmp_path: Path,
) -> None:
    sender = SimpleNamespace(
        send_group_message=AsyncMock(),
        send_private_message=AsyncMock(return_value=88888),
    )
    registry = AttachmentRegistry(
        registry_path=tmp_path / "attachment_registry.json",
        cache_dir=tmp_path / "attachments",
    )
    record = await registry.register_bytes(
        "webui",
        b"\x89PNG\r\n\x1a\n",
        kind="image",
        display_name="webui.png",
        source_kind="test",
    )
    context: dict[str, Any] = {
        "request_type": "private",
        "user_id": 42,
        "sender_id": 10001,
        "request_id": "req-webui-1",
        "runtime_config": _build_runtime_config(),
        "sender": sender,
        "attachment_registry": registry,
        "webui_session": True,
    }

    result = await execute(
        {
            "message": f'WebUI 图片\n<pic uid="{record.uid}"/>\n结束',
        },
        context,
    )

    assert result == "消息已发送（message_id=88888）"
    sent_args = sender.send_private_message.await_args
    assert "[CQ:image,file=file://" in sent_args.args[1]
    assert sent_args.kwargs["history_message"] == (
        f"WebUI 图片\n[图片 uid={record.uid} name=webui.png]\n结束"
    )
