from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import pytest

from Undefined.utils.sender import MAX_MESSAGE_LENGTH, MessageSender


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
