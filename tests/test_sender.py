from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest

from Undefined.context import RequestContext
from Undefined.utils import io as async_io
from Undefined.utils.message_targets import DeliveryAddress
from Undefined.utils.sender import AddressBoundSender, MAX_MESSAGE_LENGTH, MessageSender


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
        await sender.send_address_message(
            DeliveryAddress("wechat", 12345),
            "hello",
        )
        assert ctx.get_resource("message_sent_this_turn") is True

    service.send_text.assert_awaited_once_with(12345, "hello")
    history_mock = cast(AsyncMock, sender.history_manager.add_private_message)
    assert history_mock.await_args is not None
    assert history_mock.await_args.kwargs["transport"] == {
        "channel": "wechat",
        "address": "wechat:12345",
    }


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
async def test_send_wechat_record_rejects_before_partial_text_send(
    sender: MessageSender,
    tmp_path: Path,
) -> None:
    voice_path = tmp_path / "voice.silk"
    await async_io.write_bytes(voice_path, b"silk")
    service = SimpleNamespace(
        send_text=AsyncMock(return_value="client-1"),
        send_file=AsyncMock(return_value="client-2"),
    )
    sender.set_weixin_service(service)

    with pytest.raises(ValueError, match="不支持发送语音"):
        await sender.send_address_message(
            DeliveryAddress("wechat", 12345),
            f"hello[CQ:record,file={voice_path.resolve().as_uri()}]",
        )

    service.send_text.assert_not_awaited()
    service.send_file.assert_not_awaited()


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
    service = SimpleNamespace(
        send_text=AsyncMock(return_value="client-text"),
        send_file=AsyncMock(return_value="client-file"),
    )
    sender.set_weixin_service(service)
    bound_sender = AddressBoundSender(sender, DeliveryAddress("wechat", 12345))
    nodes = [
        {
            "type": "node",
            "data": {
                "content": [
                    {
                        "type": "image",
                        "data": {"file": image_path.resolve().as_uri()},
                    },
                    {"type": "at", "data": {"qq": "67890"}},
                    {"type": "text", "data": {"text": "caption"}},
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

    service.send_file.assert_awaited_once()
    service.send_text.assert_awaited_once_with(12345, "caption")
    registry.register_local_file.assert_awaited_once()
    history_mock = cast(AsyncMock, sender.history_manager.add_private_message)
    history_mock.assert_awaited_once()
    assert history_mock.await_args is not None
    history_kwargs = history_mock.await_args.kwargs
    assert history_kwargs["attachments"][0]["uid"] == "pic_forward"
    assert "pic_forward" in history_kwargs["text_content"]
    assert history_kwargs["transport"] == {
        "channel": "wechat",
        "address": "wechat:12345",
    }
    assert "type=at" in caplog.text
