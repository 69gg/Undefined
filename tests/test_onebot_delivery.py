from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

from Undefined.context import RequestContext
from Undefined.onebot.client import (
    OneBotClient,
    OneBotDeliveryUncertainError,
)
from Undefined.utils.coerce import was_message_sent


class _RespondingWebSocket:
    close_code: int | None = None

    def __init__(
        self,
        client: OneBotClient,
        response: dict[str, Any],
    ) -> None:
        self.client = client
        self.response = response
        self.send_count = 0

    async def send(self, payload: str) -> None:
        self.send_count += 1
        request = json.loads(payload)
        echo = str(request["echo"])
        response = {**self.response, "echo": echo}
        self.client._pending_responses[echo].set_result(response)


@pytest.mark.asyncio
async def test_upload_group_file_does_not_fallback_or_repeat_after_timeout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = OneBotClient("ws://example.invalid")
    websocket = _RespondingWebSocket(
        client,
        {
            "status": "failed",
            "retcode": 1200,
            "message": (
                "Timeout: NTEvent serviceAndMethod:NodeIKernelMsgService/sendMsg "
                "ListenerName:NodeIKernelMsgListener/onMsgInfoListUpdate"
            ),
        },
    )
    client.ws = cast(Any, websocket)
    fallback = AsyncMock(return_value={"status": "ok"})
    monkeypatch.setattr(client, "send_group_message", fallback)
    file_path = tmp_path / "song.mp3"

    async with RequestContext(
        request_type="group",
        group_id=10001,
        sender_id=20002,
    ) as request_context:
        with pytest.raises(OneBotDeliveryUncertainError):
            await client.upload_group_file(10001, str(file_path), "song.mp3")

        with pytest.raises(OneBotDeliveryUncertainError):
            await client.upload_group_file(10001, str(file_path), "song.mp3")

        assert was_message_sent(request_context) is True

    assert websocket.send_count == 1
    fallback.assert_not_awaited()


@pytest.mark.asyncio
async def test_upload_group_file_keeps_fallback_for_definitive_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = OneBotClient("ws://example.invalid")
    upload = AsyncMock(side_effect=RuntimeError("消息体无法解析"))
    fallback = AsyncMock(return_value={"status": "ok"})
    monkeypatch.setattr(client, "_call_api", upload)
    monkeypatch.setattr(client, "send_group_message", fallback)
    file_path = tmp_path / "song.mp3"

    result = await client.upload_group_file(10001, str(file_path), "song.mp3")

    assert result == {"status": "ok"}
    fallback.assert_awaited_once()
