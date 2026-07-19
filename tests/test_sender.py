from __future__ import annotations

import logging
import nturl2path
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from weixin_ilink_client import (
    ApiError,
    HttpError,
    OutboundMediaItem,
    OutboundTextItem,
    RefMessage,
    RequestTimeoutError,
    TransportError,
    UnsupportedCapabilityError,
)

from Undefined.context import RequestContext
from Undefined.utils import io as async_io
from Undefined.utils.message_reply import ReplyContext
from Undefined.utils.message_targets import DeliveryAddress
from Undefined.utils.sender import (
    AddressBoundSender,
    MAX_MESSAGE_LENGTH,
    MessageSender,
    _file_uri_path_text,
    _get_file_size,
    _local_path_from_segment_source,
)
from Undefined.weixin.audio import PreparedWeixinVoice


@pytest.fixture
def sender() -> MessageSender:
    onebot = MagicMock()
    history_manager = MagicMock()
    history_manager.add_group_message = AsyncMock()
    history_manager.add_private_message = AsyncMock()

    config = MagicMock()
    config.is_group_allowed.return_value = True
    config.is_private_allowed.return_value = True
    config.access_control_enabled.return_value = False
    config.group_access_denied_reason.return_value = None
    config.private_access_denied_reason.return_value = None

    return MessageSender(onebot, history_manager, bot_qq=10000, config=config)


def test_file_uri_path_text_supports_windows_drive_and_unc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "Undefined.utils.sender.url2pathname",
        nturl2path.url2pathname,
    )

    assert _file_uri_path_text("file:///C:/Users/Test%20User/voice.wav") == (
        r"C:\Users\Test User\voice.wav"
    )
    assert _file_uri_path_text("file://server/share/report.zip") == (
        r"\\server\share\report.zip"
    )


@pytest.mark.asyncio
async def test_local_media_metadata_uses_async_io(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "voice.wav"
    resolved = AsyncMock(return_value=source)
    is_file = AsyncMock(return_value=True)
    get_file_size = AsyncMock(return_value=321)
    monkeypatch.setattr(async_io, "resolve_path", resolved)
    monkeypatch.setattr(async_io, "is_file", is_file)
    monkeypatch.setattr(async_io, "get_file_size", get_file_size)

    assert await _local_path_from_segment_source(source) == source
    assert await _get_file_size(source) == 321

    resolved.assert_awaited_once_with(source)
    is_file.assert_awaited_once_with(source)
    get_file_size.assert_awaited_once_with(source)


@pytest.mark.asyncio
async def test_send_group_file_registers_attachment_in_history(
    tmp_path: Path,
) -> None:
    file_path = tmp_path / "paper.pdf"
    file_path.write_bytes(b"pdf")
    onebot = MagicMock()
    onebot.upload_group_file = AsyncMock()
    history_manager = MagicMock()
    history_manager.add_group_message = AsyncMock()
    config = MagicMock()
    config.is_group_allowed.return_value = True
    config.access_control_enabled.return_value = False
    config.group_access_denied_reason.return_value = None

    record = SimpleNamespace(
        prompt_ref=lambda: {
            "uid": "file_test",
            "kind": "file",
            "media_type": "file",
            "display_name": "paper.pdf",
        }
    )
    attachment_registry = SimpleNamespace(
        register_local_file=AsyncMock(return_value=record)
    )
    sender = MessageSender(
        onebot,
        history_manager,
        bot_qq=10000,
        config=config,
        attachment_registry=attachment_registry,
    )

    await sender.send_group_file(12345, str(file_path), "paper.pdf")

    attachment_registry.register_local_file.assert_awaited_once()
    history_mock = cast(AsyncMock, history_manager.add_group_message)
    assert history_mock.await_count == 1
    assert history_mock.await_args is not None
    kwargs = history_mock.await_args.kwargs
    assert kwargs["attachments"][0]["uid"] == "file_test"
    assert "uid=file_test" in kwargs["text_content"]


@pytest.mark.asyncio
async def test_send_group_message_registers_local_cq_media(
    sender: MessageSender,
    tmp_path: Path,
) -> None:
    image_path = tmp_path / "card.png"
    video_path = tmp_path / "clip.mp4"
    image_path.write_bytes(b"png")
    video_path.write_bytes(b"video")

    image_record = SimpleNamespace(
        prompt_ref=lambda: {
            "uid": "pic_card",
            "kind": "image",
            "media_type": "image",
            "display_name": "card.png",
        }
    )
    video_record = SimpleNamespace(
        prompt_ref=lambda: {
            "uid": "file_clip",
            "kind": "video",
            "media_type": "video",
            "display_name": "clip.mp4",
        }
    )
    sender.attachment_registry = SimpleNamespace(
        register_local_file=AsyncMock(side_effect=[image_record, video_record])
    )
    sender.onebot.send_group_message = AsyncMock(  # type: ignore[method-assign]
        return_value={"message_id": 123}
    )
    message = (
        f"[CQ:image,file={image_path.resolve().as_uri()}]"
        f"[CQ:video,file={video_path.resolve().as_uri()}]"
    )

    await sender.send_group_message(12345, message, history_message="媒体预处理")

    sender.attachment_registry.register_local_file.assert_any_await(
        "group:12345",
        str(image_path.resolve()),
        kind="image",
        display_name="card.png",
        source_kind="sent_image",
        source_ref=image_path.resolve().as_uri(),
    )
    sender.attachment_registry.register_local_file.assert_any_await(
        "group:12345",
        str(video_path.resolve()),
        kind="video",
        display_name="clip.mp4",
        source_kind="sent_video",
        source_ref=video_path.resolve().as_uri(),
    )
    history_mock = cast(AsyncMock, sender.history_manager.add_group_message)
    assert history_mock.await_args is not None
    kwargs = history_mock.await_args.kwargs
    assert [item["uid"] for item in kwargs["attachments"]] == [
        "pic_card",
        "file_clip",
    ]
    assert "uid=pic_card" in kwargs["text_content"]
    assert "uid=file_clip" in kwargs["text_content"]


@pytest.mark.asyncio
async def test_send_group_forward_message_records_history(
    sender: MessageSender,
) -> None:
    onebot = cast(Any, sender.onebot)
    onebot.send_forward_msg = AsyncMock()
    nodes = [
        {
            "type": "node",
            "data": {"name": "Bot", "uin": "10000", "content": "长内容"},
        }
    ]

    await sender.send_group_forward_message(
        12345,
        nodes,
        history_message="[命令输出] 合并转发摘要",
    )

    onebot.send_forward_msg.assert_awaited_once_with(12345, nodes)
    history_mock = cast(AsyncMock, sender.history_manager.add_group_message)
    history_mock.assert_awaited_once()
    assert history_mock.await_args is not None
    kwargs = history_mock.await_args.kwargs
    assert kwargs["group_id"] == 12345
    assert kwargs["sender_id"] == 10000
    assert kwargs["text_content"] == "[命令输出] 合并转发摘要"


@pytest.mark.asyncio
async def test_send_group_forward_message_registers_nested_local_video(
    sender: MessageSender,
    tmp_path: Path,
) -> None:
    video_path = tmp_path / "clip.mp4"
    video_path.write_bytes(b"video")
    video_record = SimpleNamespace(
        prompt_ref=lambda: {
            "uid": "file_clip",
            "kind": "video",
            "media_type": "video",
            "display_name": "clip.mp4",
        }
    )
    sender.attachment_registry = SimpleNamespace(
        register_local_file=AsyncMock(return_value=video_record)
    )
    onebot = cast(Any, sender.onebot)
    onebot.send_forward_msg = AsyncMock()
    nodes = [
        {
            "type": "node",
            "data": {
                "name": "Bot",
                "uin": "10000",
                "content": [
                    {
                        "type": "video",
                        "data": {"file": video_path.resolve().as_uri()},
                    }
                ],
            },
        }
    ]

    await sender.send_group_forward_message(
        12345,
        nodes,
        history_message="[Bilibili] 合并转发摘要",
    )

    sender.attachment_registry.register_local_file.assert_awaited_once()
    history_mock = cast(AsyncMock, sender.history_manager.add_group_message)
    assert history_mock.await_args is not None
    kwargs = history_mock.await_args.kwargs
    assert kwargs["attachments"][0]["uid"] == "file_clip"
    assert "uid=file_clip" in kwargs["text_content"]


@pytest.mark.asyncio
async def test_send_private_forward_message_records_history(
    sender: MessageSender,
) -> None:
    onebot = cast(Any, sender.onebot)
    onebot.send_private_forward_msg = AsyncMock()
    nodes = [
        {
            "type": "node",
            "data": {"name": "Bot", "uin": "10000", "content": "长内容"},
        }
    ]

    await sender.send_private_forward_message(
        54321,
        nodes,
        history_message="[命令输出] 私聊合并转发摘要",
    )

    onebot.send_private_forward_msg.assert_awaited_once_with(54321, nodes)
    history_mock = cast(AsyncMock, sender.history_manager.add_private_message)
    history_mock.assert_awaited_once()
    assert history_mock.await_args is not None
    kwargs = history_mock.await_args.kwargs
    assert kwargs["user_id"] == 54321
    assert kwargs["text_content"] == "[命令输出] 私聊合并转发摘要"


@pytest.mark.asyncio
async def test_send_group_message_reads_message_id_from_onebot_envelope(
    sender: MessageSender,
) -> None:
    sender.onebot.send_group_message = AsyncMock(  # type: ignore[method-assign]
        return_value={"data": {"message_id": 123456}}
    )

    await sender.send_group_message(12345, "hello group")

    mock = cast(AsyncMock, sender.history_manager.add_group_message)
    assert mock.await_count == 1
    assert mock.await_args is not None
    assert mock.await_args.kwargs["message_id"] == 123456


@pytest.mark.asyncio
async def test_send_private_message_reads_message_id_from_chunked_envelope(
    sender: MessageSender,
) -> None:
    sender.onebot.send_private_message = AsyncMock(  # type: ignore[method-assign]
        side_effect=[
            {"data": {"message_id": "223344"}},
            {"data": {"message_id": "223345"}},
        ]
    )
    long_message = f"{'a' * (MAX_MESSAGE_LENGTH - 500)}\n{'b' * 700}"

    await sender.send_private_message(54321, long_message)

    mock = cast(AsyncMock, sender.history_manager.add_private_message)
    assert mock.await_count == 1
    assert mock.await_args is not None
    assert mock.await_args.kwargs["message_id"] == 223344


@pytest.mark.asyncio
async def test_send_private_message_falls_back_to_group_temp_session(
    sender: MessageSender,
) -> None:
    sender.onebot.get_group_list = AsyncMock(  # type: ignore[method-assign]
        return_value=[{"group_id": 11111}, {"group_id": 22222}]
    )
    sender.onebot.send_private_message = AsyncMock(  # type: ignore[method-assign]
        side_effect=[
            RuntimeError("direct failed"),
            RuntimeError("group 11111 failed"),
            {"data": {"message_id": 998877}},
        ]
    )

    await sender.send_private_message(54321, "hello temp session")

    send_mock = sender.onebot.send_private_message
    assert send_mock.await_count == 3
    assert "group_id" not in send_mock.await_args_list[0].kwargs
    assert send_mock.await_args_list[1].kwargs["group_id"] == 11111
    assert send_mock.await_args_list[2].kwargs["group_id"] == 22222

    history_mock = cast(AsyncMock, sender.history_manager.add_private_message)
    assert history_mock.await_count == 1
    assert history_mock.await_args is not None
    assert history_mock.await_args.kwargs["message_id"] == 998877


@pytest.mark.asyncio
async def test_send_private_message_prefers_context_group_before_group_scan(
    sender: MessageSender,
) -> None:
    sender.onebot.get_group_list = AsyncMock(  # type: ignore[method-assign]
        return_value=[{"group_id": 22222}, {"group_id": 11111}]
    )
    sender.onebot.send_private_message = AsyncMock(  # type: ignore[method-assign]
        side_effect=[
            RuntimeError("direct failed"),
            {"data": {"message_id": 123456}},
        ]
    )

    await sender.send_private_message(
        54321,
        "hello context group",
        preferred_temp_group_id=11111,
    )

    send_mock = sender.onebot.send_private_message
    assert send_mock.await_count == 2
    assert "group_id" not in send_mock.await_args_list[0].kwargs
    assert send_mock.await_args_list[1].kwargs["group_id"] == 11111
    sender.onebot.get_group_list.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_private_message_chunked_reuses_successful_temp_session_group(
    sender: MessageSender,
) -> None:
    sender.onebot.get_group_list = AsyncMock(  # type: ignore[method-assign]
        return_value=[{"group_id": 33333}, {"group_id": 44444}]
    )
    sender.onebot.send_private_message = AsyncMock(  # type: ignore[method-assign]
        side_effect=[
            RuntimeError("direct failed"),
            {"data": {"message_id": "223344"}},
            {"data": {"message_id": "223345"}},
        ]
    )
    long_message = f"{'a' * (MAX_MESSAGE_LENGTH - 500)}\n{'b' * 700}"

    await sender.send_private_message(54321, long_message)

    send_mock = sender.onebot.send_private_message
    assert send_mock.await_count == 3
    assert "group_id" not in send_mock.await_args_list[0].kwargs
    assert send_mock.await_args_list[1].kwargs["group_id"] == 33333
    assert send_mock.await_args_list[2].kwargs["group_id"] == 33333
    sender.onebot.get_group_list.assert_awaited_once()

    history_mock = cast(AsyncMock, sender.history_manager.add_private_message)
    assert history_mock.await_count == 1
    assert history_mock.await_args is not None
    assert history_mock.await_args.kwargs["message_id"] == 223344


@pytest.mark.asyncio
async def test_send_wechat_message_routes_text_and_records_transport(
    sender: MessageSender,
) -> None:
    service = SimpleNamespace(send_text=AsyncMock(return_value="client-1"))
    sender.set_weixin_service(service)

    async with RequestContext("private", user_id=12345, sender_id=12345) as ctx:
        sent_message_id = await sender.send_address_message(
            DeliveryAddress("wechat", 12345),
            "hello",
        )
        assert ctx.get_resource("message_sent_this_turn") is True

    assert sent_message_id == "client-1"
    service.send_text.assert_awaited_once_with(12345, "hello")
    history_mock = cast(AsyncMock, sender.history_manager.add_private_message)
    assert history_mock.await_args is not None
    assert history_mock.await_args.kwargs["message_id"] == "client-1"
    transport = history_mock.await_args.kwargs["transport"]
    assert transport["channel"] == "wechat"
    assert transport["address"] == "wechat:12345"
    assert transport["message_ids"] == ["client-1"]
    assert isinstance(transport["sent_at_ms"], int)


@pytest.mark.asyncio
async def test_send_wechat_native_reply_uses_same_route_history(
    sender: MessageSender,
) -> None:
    quoted_attachment: dict[str, str] = {
        "uid": "pic_secret",
        "kind": "image",
        "media_type": "image",
        "display_name": "/srv/private/quoted.png",
    }
    record: dict[str, Any] = {
        "message_id": "inbound-1",
        "display_name": "微信用户",
        "message": '旧消息 <attachment uid="pic_secret"/>',
        "attachments": [quoted_attachment],
        "transport": {
            "channel": "wechat",
            "address": "wechat:12345",
        },
    }
    lookup = AsyncMock(return_value=record)
    cast(Any, sender.history_manager).find_private_message_by_id = lookup
    service = SimpleNamespace(send_text=AsyncMock(return_value="client-reply"))
    sender.set_weixin_service(service)

    sent_message_id = await sender.send_address_message(
        DeliveryAddress("wechat", 12345),
        "收到",
        reply_to="inbound-1",
    )

    assert sent_message_id == "client-reply"
    lookup.assert_awaited_once_with(
        12345,
        "inbound-1",
        channel="wechat",
        address="wechat:12345",
    )
    send_call = service.send_text.await_args
    assert send_call is not None
    assert send_call.args == (12345, "收到")
    reference = send_call.kwargs["reference"]
    assert reference == RefMessage.from_text(
        "微信用户",
        "旧消息\n[图片: quoted.png]",
    )
    assert "pic_secret" not in reference.message_item.text
    assert "/srv/private" not in reference.message_item.text

    history_mock = cast(AsyncMock, sender.history_manager.add_private_message)
    assert history_mock.await_args is not None
    history_kwargs = history_mock.await_args.kwargs
    assert history_kwargs["reply_context"] == ReplyContext(
        title="微信用户",
        message_id="inbound-1",
        text='旧消息 <attachment uid="pic_secret"/>',
        attachments=(quoted_attachment,),
    )
    assert history_kwargs["transport"]["reply_to"] == "inbound-1"
    assert history_kwargs["transport"]["reply_mode"] == "native"


@pytest.mark.asyncio
async def test_send_wechat_reply_rejects_target_outside_current_route(
    sender: MessageSender,
) -> None:
    lookup = AsyncMock(return_value=None)
    cast(Any, sender.history_manager).find_private_message_by_id = lookup
    service = SimpleNamespace(send_text=AsyncMock(return_value="client-reply"))
    sender.set_weixin_service(service)

    with pytest.raises(ValueError, match="不在当前微信会话历史中"):
        await sender.send_address_message(
            DeliveryAddress("wechat", 12345),
            "不会发送",
            reply_to="other-route-message",
        )

    service.send_text.assert_not_awaited()
    cast(AsyncMock, sender.history_manager.add_private_message).assert_not_awaited()


@pytest.mark.asyncio
async def test_send_wechat_reply_falls_back_only_after_explicit_rejection(
    sender: MessageSender,
) -> None:
    cast(Any, sender.history_manager).find_private_message_by_id = AsyncMock(
        return_value={
            "message_id": "inbound-2",
            "display_name": "微信用户",
            "message": "旧消息",
            "transport": {
                "channel": "wechat",
                "address": "wechat:12345",
            },
        }
    )
    service = SimpleNamespace(
        send_text=AsyncMock(
            side_effect=[
                UnsupportedCapabilityError("reference rejected"),
                "client-fallback",
            ]
        )
    )
    sender.set_weixin_service(service)

    sent_message_id = await sender.send_address_message(
        DeliveryAddress("wechat", 12345),
        "降级正文",
        reply_to="inbound-2",
    )

    assert sent_message_id == "client-fallback"
    assert service.send_text.await_count == 2
    first_call, fallback_call = service.send_text.await_args_list
    assert isinstance(first_call.kwargs["reference"], RefMessage)
    assert fallback_call.args == (
        12345,
        "> **引用 微信用户**\n> 旧消息\n\n降级正文",
    )
    assert fallback_call.kwargs == {}
    history_mock = cast(AsyncMock, sender.history_manager.add_private_message)
    assert history_mock.await_args is not None
    assert history_mock.await_args.kwargs["transport"]["reply_mode"] == (
        "markdown_fallback"
    )


@pytest.mark.asyncio
async def test_send_wechat_reply_does_not_retry_ambiguous_transport_failure(
    sender: MessageSender,
) -> None:
    cast(Any, sender.history_manager).find_private_message_by_id = AsyncMock(
        return_value={
            "message_id": "inbound-3",
            "display_name": "微信用户",
            "message": "旧消息",
            "transport": {
                "channel": "wechat",
                "address": "wechat:12345",
            },
        }
    )
    service = SimpleNamespace(
        send_text=AsyncMock(side_effect=TransportError("offline"))
    )
    sender.set_weixin_service(service)

    with pytest.raises(TransportError, match="offline"):
        await sender.send_address_message(
            DeliveryAddress("wechat", 12345),
            "不应重发",
            reply_to="inbound-3",
        )

    assert service.send_text.await_count == 1
    cast(AsyncMock, sender.history_manager.add_private_message).assert_not_awaited()


@pytest.mark.asyncio
async def test_send_wechat_media_only_reply_attaches_native_reference(
    sender: MessageSender,
    tmp_path: Path,
) -> None:
    image_path = tmp_path / "reply.png"
    await async_io.write_bytes(image_path, b"png")
    cast(Any, sender.history_manager).find_private_message_by_id = AsyncMock(
        return_value={
            "message_id": "inbound-4",
            "display_name": "微信用户",
            "message": "旧消息",
            "transport": {
                "channel": "wechat",
                "address": "wechat:12345",
            },
        }
    )
    service = SimpleNamespace(
        send_text=AsyncMock(return_value="client-text"),
        send_file=AsyncMock(return_value="client-media"),
        validate_media_files=AsyncMock(),
    )
    sender.set_weixin_service(service)

    sent_message_id = await sender.send_address_message(
        DeliveryAddress("wechat", 12345),
        f"[CQ:image,file={image_path.resolve().as_uri()}]",
        reply_to="inbound-4",
        auto_history=False,
    )

    assert sent_message_id == "client-media"
    service.send_text.assert_not_awaited()
    send_call = service.send_file.await_args
    assert send_call is not None
    assert send_call.args == (12345, image_path.resolve())
    assert send_call.kwargs["reference"] == RefMessage.from_text(
        "微信用户",
        "旧消息",
    )


@pytest.mark.asyncio
async def test_send_wechat_message_splits_long_text_without_duplicate_history(
    sender: MessageSender,
) -> None:
    service = SimpleNamespace(send_text=AsyncMock(return_value="client-1"))
    sender.set_weixin_service(service)
    message = f"{'a' * (MAX_MESSAGE_LENGTH - 5)}\n{'b' * 10}"

    await sender.send_address_message(DeliveryAddress("wechat", 12345), message)

    assert [call.args[1] for call in service.send_text.await_args_list] == [
        f"{'a' * (MAX_MESSAGE_LENGTH - 5)}\n",
        "b" * 10,
    ]
    history_mock = cast(AsyncMock, sender.history_manager.add_private_message)
    history_mock.assert_awaited_once()
    assert history_mock.await_args is not None
    assert history_mock.await_args.kwargs["text_content"] == message


@pytest.mark.asyncio
@pytest.mark.parametrize("segment_type", ["record", "audio"])
async def test_send_wechat_audio_preflights_and_sends_native_voice(
    sender: MessageSender,
    tmp_path: Path,
    segment_type: str,
) -> None:
    voice_path = tmp_path / "voice.wav"
    await async_io.write_bytes(voice_path, b"wav")
    prepared = PreparedWeixinVoice(
        content=b"\x02#!SILK_V3voice",
        duration_ms=200,
    )
    events: list[str] = []

    async def validate_media_files(_paths: list[Path]) -> None:
        events.append("validate")

    async def prepare_voice(_path: Path) -> PreparedWeixinVoice:
        events.append("prepare")
        return prepared

    async def send_text(_user_id: int, _text: str, **_kwargs: Any) -> str:
        events.append("text")
        return "client-text"

    async def send_prepared_voice(
        _user_id: int,
        value: PreparedWeixinVoice,
        **_kwargs: Any,
    ) -> str:
        assert value is prepared
        events.append("voice")
        return "client-voice"

    service = SimpleNamespace(
        validate_media_files=validate_media_files,
        prepare_voice=prepare_voice,
        send_text=send_text,
        send_prepared_voice=send_prepared_voice,
    )
    sender.set_weixin_service(service)

    await sender.send_address_message(
        DeliveryAddress("wechat", 12345),
        f"hello[CQ:{segment_type},file={voice_path.resolve().as_uri()}]",
        auto_history=False,
    )

    assert events == ["validate", "prepare", "text", "voice"]


@pytest.mark.asyncio
async def test_send_wechat_media_preflight_failure_sends_nothing(
    sender: MessageSender,
    tmp_path: Path,
) -> None:
    file_path = tmp_path / "oversized.bin"
    await async_io.write_bytes(file_path, b"file")
    service = SimpleNamespace(
        validate_media_files=AsyncMock(side_effect=ValueError("too large")),
        send_text=AsyncMock(return_value="client-text"),
        send_file=AsyncMock(return_value="client-file"),
    )
    sender.set_weixin_service(service)

    with pytest.raises(ValueError, match="too large"):
        await sender.send_address_message(
            DeliveryAddress("wechat", 12345),
            f"before[CQ:file,file={file_path.resolve().as_uri()}]",
        )

    service.send_text.assert_not_awaited()
    service.send_file.assert_not_awaited()
    cast(AsyncMock, sender.history_manager.add_private_message).assert_not_awaited()


@pytest.mark.asyncio
async def test_send_wechat_file_records_client_id_and_send_time(
    sender: MessageSender,
    tmp_path: Path,
) -> None:
    file_path = tmp_path / "report.txt"
    await async_io.write_text(file_path, "report")
    service = SimpleNamespace(send_file=AsyncMock(return_value="client-file"))
    sender.set_weixin_service(service)

    await sender.send_address_file(
        DeliveryAddress("wechat", 12345),
        str(file_path),
    )

    history_mock = cast(AsyncMock, sender.history_manager.add_private_message)
    assert history_mock.await_args is not None
    history_kwargs = history_mock.await_args.kwargs
    assert history_kwargs["message_id"] == "client-file"
    assert history_kwargs["transport"]["message_ids"] == ["client-file"]
    assert isinstance(history_kwargs["transport"]["sent_at_ms"], int)


@pytest.mark.asyncio
async def test_send_wechat_file_enforces_private_access_control(
    sender: MessageSender,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    file_path = tmp_path / "report.txt"
    await async_io.write_text(file_path, "report")
    service = SimpleNamespace(send_file=AsyncMock(return_value="client-1"))
    sender.set_weixin_service(service)
    cast(MagicMock, sender.config.is_private_allowed).return_value = False
    cast(MagicMock, sender.config.access_control_enabled).return_value = True
    cast(
        MagicMock, sender.config.private_access_denied_reason
    ).return_value = "blacklist"

    with caplog.at_level(logging.WARNING, logger="Undefined.utils.sender"):
        with pytest.raises(
            PermissionError,
            match=r"reason=blacklist user_id=12345 enabled=True",
        ):
            await sender.send_address_file(
                DeliveryAddress("wechat", 12345),
                str(file_path),
            )

    service.send_file.assert_not_awaited()
    assert "已拦截微信文件发送" in caplog.text
    assert "reason=blacklist" in caplog.text
    assert "access enabled=True" in caplog.text


@pytest.mark.asyncio
async def test_send_wechat_message_logs_access_control_details(
    sender: MessageSender,
    caplog: pytest.LogCaptureFixture,
) -> None:
    cast(MagicMock, sender.config.is_private_allowed).return_value = False
    cast(MagicMock, sender.config.access_control_enabled).return_value = True
    cast(
        MagicMock, sender.config.private_access_denied_reason
    ).return_value = "allowlist"

    with (
        caplog.at_level(logging.WARNING, logger="Undefined.utils.sender"),
        pytest.raises(
            PermissionError,
            match=r"reason=allowlist user_id=12345 enabled=True",
        ),
    ):
        await sender.send_address_message(
            DeliveryAddress("wechat", 12345),
            "blocked",
        )

    assert "已拦截微信消息发送" in caplog.text
    assert "reason=allowlist" in caplog.text
    assert "access enabled=True" in caplog.text


@pytest.mark.asyncio
async def test_send_wechat_media_skips_attachment_registry_without_history(
    sender: MessageSender,
    tmp_path: Path,
) -> None:
    image_path = tmp_path / "no-history.png"
    await async_io.write_bytes(image_path, b"png")
    registry = SimpleNamespace(register_local_file=AsyncMock())
    sender.attachment_registry = registry
    service = SimpleNamespace(
        send_text=AsyncMock(return_value="client-text"),
        send_file=AsyncMock(return_value="client-file"),
        validate_media_files=AsyncMock(),
    )
    sender.set_weixin_service(service)

    await sender.send_address_message(
        DeliveryAddress("wechat", 12345),
        f"[CQ:image,file={image_path.resolve().as_uri()}]",
        auto_history=False,
    )

    service.send_text.assert_not_awaited()
    service.send_file.assert_awaited_once()
    registry.register_local_file.assert_not_awaited()
    cast(AsyncMock, sender.history_manager.add_private_message).assert_not_awaited()


@pytest.mark.asyncio
async def test_send_wechat_media_omits_local_path_from_text(
    sender: MessageSender,
    tmp_path: Path,
) -> None:
    image_path = tmp_path / "captioned.png"
    await async_io.write_bytes(image_path, b"png")
    service = SimpleNamespace(
        send_text=AsyncMock(return_value="client-text"),
        send_file=AsyncMock(return_value="client-file"),
        validate_media_files=AsyncMock(),
    )
    sender.set_weixin_service(service)

    await sender.send_address_message(
        DeliveryAddress("wechat", 12345),
        f"图片说明\n[CQ:image,file={image_path.resolve().as_uri()}]",
        auto_history=False,
    )

    service.send_text.assert_awaited_once_with(12345, "图片说明")
    service.send_file.assert_awaited_once_with(
        12345,
        image_path.resolve(),
        name="captioned.png",
        kind="image",
    )


@pytest.mark.asyncio
async def test_send_wechat_mixed_segments_preserves_original_order(
    sender: MessageSender,
    tmp_path: Path,
) -> None:
    image_path = tmp_path / "ordered.png"
    file_path = tmp_path / "ordered.txt"
    await async_io.write_bytes(image_path, b"png")
    await async_io.write_text(file_path, "file")
    events: list[tuple[str, str]] = []

    async def send_text(user_id: int, text: str, **kwargs: Any) -> str:
        del user_id, kwargs
        events.append(("text", text))
        return f"text-{len(events)}"

    async def send_file(
        user_id: int,
        path: Path,
        **kwargs: Any,
    ) -> str:
        del user_id, kwargs
        events.append(("file", path.name))
        return f"file-{len(events)}"

    sender.set_weixin_service(
        SimpleNamespace(
            send_text=send_text,
            send_file=send_file,
            validate_media_files=AsyncMock(),
        )
    )
    message = (
        f"A[CQ:image,file={image_path.resolve().as_uri()}]"
        f"B[CQ:file,file={file_path.resolve().as_uri()}]C"
    )

    await sender.send_address_message(
        DeliveryAddress("wechat", 12345),
        message,
        auto_history=False,
    )

    assert events == [
        ("text", "A"),
        ("file", "ordered.png"),
        ("text", "B"),
        ("file", "ordered.txt"),
        ("text", "C"),
    ]


@pytest.mark.asyncio
async def test_send_wechat_media_skips_attachment_registry_when_send_fails(
    sender: MessageSender,
    tmp_path: Path,
) -> None:
    image_path = tmp_path / "failed.png"
    await async_io.write_bytes(image_path, b"png")
    registry = SimpleNamespace(register_local_file=AsyncMock())
    sender.attachment_registry = registry
    service = SimpleNamespace(
        send_text=AsyncMock(return_value="client-text"),
        send_file=AsyncMock(side_effect=RuntimeError("failed")),
        validate_media_files=AsyncMock(),
    )
    sender.set_weixin_service(service)

    with pytest.raises(RuntimeError, match="failed"):
        await sender.send_address_message(
            DeliveryAddress("wechat", 12345),
            f"[CQ:image,file={image_path.resolve().as_uri()}]",
        )

    registry.register_local_file.assert_not_awaited()
    cast(AsyncMock, sender.history_manager.add_private_message).assert_not_awaited()


@pytest.mark.asyncio
async def test_send_wechat_file_segment_registers_history_attachment(
    sender: MessageSender,
    tmp_path: Path,
) -> None:
    file_path = tmp_path / "result.zip"
    await async_io.write_bytes(file_path, b"zip")
    record = SimpleNamespace(
        prompt_ref=lambda: {
            "uid": "file_result",
            "kind": "file",
            "media_type": "file",
            "display_name": file_path.name,
        }
    )
    sender.attachment_registry = SimpleNamespace(
        register_local_file=AsyncMock(return_value=record)
    )
    service = SimpleNamespace(
        send_file=AsyncMock(return_value="client-file"),
        validate_media_files=AsyncMock(),
    )
    sender.set_weixin_service(service)

    await sender.send_address_message(
        DeliveryAddress("wechat", 12345),
        f"[CQ:file,file={file_path.resolve().as_uri()}]",
    )

    sender.attachment_registry.register_local_file.assert_awaited_once_with(
        "private:12345",
        str(file_path.resolve()),
        kind="file",
        display_name="result.zip",
        source_kind="sent_file",
        source_ref=file_path.resolve().as_uri(),
    )
    history_mock = cast(AsyncMock, sender.history_manager.add_private_message)
    assert history_mock.await_args is not None
    assert history_mock.await_args.kwargs["attachments"][0]["uid"] == "file_result"
    assert "uid=file_result" in history_mock.await_args.kwargs["text_content"]


@pytest.mark.asyncio
async def test_send_wechat_forward_registers_media_and_logs_unsupported_segments(
    sender: MessageSender,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    image_path = tmp_path / "forward.png"
    await async_io.write_bytes(image_path, b"png")
    record = SimpleNamespace(
        prompt_ref=lambda: {
            "uid": "pic_forward",
            "kind": "image",
            "media_type": "image",
            "display_name": image_path.name,
        }
    )
    registry = SimpleNamespace(register_local_file=AsyncMock(return_value=record))
    sender.attachment_registry = registry
    events: list[tuple[str, str]] = []

    async def send_text(_user_id: int, text: str, **_kwargs: Any) -> str:
        events.append(("text", text))
        return "client-text"

    async def send_file(_user_id: int, path: str | Path, **_kwargs: Any) -> str:
        events.append(("file", Path(path).name))
        return "client-file"

    service = SimpleNamespace(
        send_text=send_text,
        send_file=send_file,
        validate_media_files=AsyncMock(),
    )
    sender.set_weixin_service(service)
    bound_sender = AddressBoundSender(sender, DeliveryAddress("wechat", 12345))
    nodes = [
        {
            "type": "node",
            "data": {
                "content": [
                    {"type": "text", "data": {"text": "A"}},
                    {
                        "type": "image",
                        "data": {"file": image_path.resolve().as_uri()},
                    },
                    {"type": "at", "data": {"qq": "67890"}},
                    {"type": "text", "data": {"text": "B"}},
                ]
            },
        }
    ]

    with caplog.at_level(logging.WARNING, logger="Undefined.utils.sender"):
        await bound_sender.send_private_forward_message(
            12345,
            nodes,
            history_message="[命令输出] 微信转发摘要",
        )

    assert events == [
        ("text", "**转发消息**\nA"),
        ("file", "forward.png"),
        ("text", "B"),
    ]
    registry.register_local_file.assert_awaited_once()
    history_mock = cast(AsyncMock, sender.history_manager.add_private_message)
    history_mock.assert_awaited_once()
    assert history_mock.await_args is not None
    history_kwargs = history_mock.await_args.kwargs
    assert history_kwargs["attachments"][0]["uid"] == "pic_forward"
    assert "pic_forward" in history_kwargs["text_content"]
    assert history_kwargs["transport"]["channel"] == "wechat"
    assert history_kwargs["transport"]["address"] == "wechat:12345"
    assert isinstance(history_kwargs["transport"]["sent_at_ms"], int)
    assert "type=at" in caplog.text


@pytest.mark.asyncio
async def test_send_wechat_forward_uses_ordered_multi_item_message(
    sender: MessageSender,
    tmp_path: Path,
) -> None:
    image_path = tmp_path / "forward.png"
    await async_io.write_bytes(image_path, b"png")
    weixin_config = cast(Any, sender.config.weixin)
    weixin_config.multi_item_messages_enabled = True
    weixin_config.multi_item_max_items = 10
    weixin_config.media_max_size_mb = 100
    service = SimpleNamespace(
        send_items=AsyncMock(return_value="bundle-1"),
        validate_media_files=AsyncMock(),
    )
    sender.set_weixin_service(service)
    bound_sender = AddressBoundSender(sender, DeliveryAddress("wechat", 12345))

    await bound_sender.send_private_forward_message(
        12345,
        [
            {
                "type": "node",
                "data": {
                    "name": "Bot",
                    "content": [
                        {"type": "text", "data": {"text": "A"}},
                        {
                            "type": "image",
                            "data": {"file": image_path.resolve().as_uri()},
                        },
                        {"type": "text", "data": {"text": "B"}},
                    ],
                },
            }
        ],
        history_message="微信转发摘要",
        auto_history=False,
    )

    service.send_items.assert_awaited_once()
    send_call = service.send_items.await_args
    assert send_call is not None
    assert send_call.args[0] == 12345
    items = send_call.args[1]
    assert len(items) == 3
    assert isinstance(items[0], OutboundTextItem)
    assert items[0].text == "**Bot**\nA"
    assert isinstance(items[1], OutboundMediaItem)
    assert items[1].content == b"png"
    assert isinstance(items[2], OutboundTextItem)
    assert items[2].text == "B"


@pytest.mark.asyncio
async def test_send_wechat_forward_falls_back_after_definitive_bundle_rejection(
    sender: MessageSender,
) -> None:
    weixin_config = cast(Any, sender.config.weixin)
    weixin_config.multi_item_messages_enabled = True
    weixin_config.multi_item_max_items = 10
    weixin_config.media_max_size_mb = 100
    service = SimpleNamespace(
        send_items=AsyncMock(side_effect=ApiError(40001, "sendmessage")),
        send_text=AsyncMock(return_value="text-1"),
    )
    sender.set_weixin_service(service)
    bound_sender = AddressBoundSender(sender, DeliveryAddress("wechat", 12345))

    await bound_sender.send_private_forward_message(
        12345,
        [{"type": "node", "data": {"name": "Bot", "content": "报告"}}],
        history_message="微信转发摘要",
        auto_history=False,
    )

    service.send_items.assert_awaited_once()
    service.send_text.assert_awaited_once_with(12345, "**Bot**\n报告")


@pytest.mark.asyncio
async def test_send_wechat_forward_does_not_duplicate_ambiguous_bundle_timeout(
    sender: MessageSender,
) -> None:
    weixin_config = cast(Any, sender.config.weixin)
    weixin_config.multi_item_messages_enabled = True
    weixin_config.multi_item_max_items = 10
    weixin_config.media_max_size_mb = 100
    service = SimpleNamespace(
        send_items=AsyncMock(side_effect=RequestTimeoutError("sendmessage timed out")),
        send_text=AsyncMock(return_value="text-1"),
    )
    sender.set_weixin_service(service)
    bound_sender = AddressBoundSender(sender, DeliveryAddress("wechat", 12345))

    with pytest.raises(RequestTimeoutError):
        await bound_sender.send_private_forward_message(
            12345,
            [{"type": "node", "data": {"name": "Bot", "content": "报告"}}],
            history_message="微信转发摘要",
            auto_history=False,
        )

    service.send_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_wechat_forward_does_not_fallback_after_rate_limit(
    sender: MessageSender,
) -> None:
    weixin_config = cast(Any, sender.config.weixin)
    weixin_config.multi_item_messages_enabled = True
    weixin_config.multi_item_max_items = 10
    weixin_config.media_max_size_mb = 100
    service = SimpleNamespace(
        send_items=AsyncMock(side_effect=HttpError(429, "sendmessage")),
        send_text=AsyncMock(return_value="text-1"),
    )
    sender.set_weixin_service(service)
    bound_sender = AddressBoundSender(sender, DeliveryAddress("wechat", 12345))

    with pytest.raises(HttpError):
        await bound_sender.send_private_forward_message(
            12345,
            [{"type": "node", "data": {"name": "Bot", "content": "报告"}}],
            history_message="微信转发摘要",
            auto_history=False,
        )

    service.send_text.assert_not_awaited()
