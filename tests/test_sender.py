from __future__ import annotations

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
