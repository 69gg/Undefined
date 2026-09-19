from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

from Undefined.context import RequestContext
from Undefined.config.onebot import FileSendSettings
from Undefined.onebot.file_errors import OneBotAPIError
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
        self.requests: list[dict[str, Any]] = []

    async def send(self, payload: str) -> None:
        self.send_count += 1
        request = json.loads(payload)
        self.requests.append(request)
        echo = str(request["echo"])
        response = {**self.response, "echo": echo}
        self.client._pending_responses[echo].set_result(response)


class _SilentWebSocket:
    close_code: int | None = None

    def __init__(self) -> None:
        self.sent = asyncio.Event()

    async def send(self, payload: str) -> None:
        self.sent.set()


@pytest.mark.asyncio
async def test_delivery_cancellation_propagates_and_blocks_repeat() -> None:
    client = OneBotClient(
        "ws://example.invalid", config_getter=lambda: FileSendSettings("local")
    )
    websocket = _SilentWebSocket()
    client.ws = cast(Any, websocket)

    async with RequestContext(
        request_type="group",
        group_id=10001,
        sender_id=20002,
    ) as request_context:
        task = asyncio.create_task(client.send_group_message(10001, "hello"))
        await websocket.sent.wait()
        task.cancel()
        # 取消必须原样传播，不能被改写成普通投递错误。
        with pytest.raises(asyncio.CancelledError):
            await task

        # 请求可能已发出：同一请求内相同投递仍禁止重发。
        with pytest.raises(OneBotDeliveryUncertainError):
            await client.send_group_message(10001, "hello")
        assert was_message_sent(request_context) is True

    assert not client._pending_responses


@pytest.mark.parametrize("target_type", ["group", "private"])
@pytest.mark.parametrize("upload_file", [False, True])
async def test_default_client_preserves_local_file_delivery(
    tmp_path: Path, target_type: str, upload_file: bool
) -> None:
    client = OneBotClient("ws://example.invalid")
    websocket = _RespondingWebSocket(client, {"status": "ok"})
    client.ws = cast(Any, websocket)
    # 本地模式允许把 Bot 上不存在的路径交给协议端，不会读取或上传该文件。
    path = tmp_path / "legacy.png"
    media = [{"type": "image", "data": {"file": str(path)}}]
    if upload_file:
        if target_type == "group":
            await client.upload_group_file(1, str(path))
        else:
            await client.upload_private_file(1, str(path))
    elif target_type == "group":
        await client.send_group_message(1, media)
    else:
        await client.send_private_message(1, media)
    assert websocket.send_count == 1
    request = websocket.requests[0]
    if upload_file:
        assert request["action"] == f"upload_{target_type}_file"
        assert request["params"]["file"] == path.as_uri()
        assert request["params"]["name"] == path.name
    else:
        assert request["action"] == f"send_{target_type}_msg"
        assert request["params"]["message"] == media


@pytest.mark.asyncio
async def test_upload_group_file_does_not_fallback_or_repeat_after_timeout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = OneBotClient(
        "ws://example.invalid", config_getter=lambda: FileSendSettings("local")
    )
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
    client = OneBotClient(
        "ws://example.invalid", config_getter=lambda: FileSendSettings("local")
    )
    upload = AsyncMock(
        side_effect=[OneBotAPIError("消息体无法解析", 1200), {"status": "ok"}]
    )
    monkeypatch.setattr(client, "_call_api_raw", upload)
    file_path = tmp_path / "song.mp3"

    result = await client.upload_group_file(10001, str(file_path), "song.mp3")

    assert result == {"status": "ok"}
    assert [call.args[0] for call in upload.await_args_list] == [
        "upload_group_file",
        "send_group_msg",
    ]
    assert (
        upload.await_args_list[0].args[1]["file"]
        == upload.await_args_list[1].args[1]["message"][0]["data"]["file"]
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("target_type", ["group", "private"])
async def test_uncertain_message_delivery_respects_mark_sent_false(
    target_type: str,
) -> None:
    client = OneBotClient("ws://example.invalid")
    websocket = _RespondingWebSocket(
        client,
        {
            "status": "failed",
            "retcode": 1200,
            "message": "Timeout while waiting for sendMsg",
        },
    )
    client.ws = cast(Any, websocket)

    async with RequestContext(
        request_type=target_type,
        group_id=10001 if target_type == "group" else None,
        user_id=20002 if target_type == "private" else None,
        sender_id=20002,
    ) as request_context:
        for _ in range(2):
            with pytest.raises(OneBotDeliveryUncertainError):
                if target_type == "group":
                    await client.send_group_message(
                        10001,
                        "background announcement",
                        mark_sent=False,
                    )
                else:
                    await client.send_private_message(
                        20002,
                        "background announcement",
                        mark_sent=False,
                    )

        assert was_message_sent(request_context) is False

    assert websocket.send_count == 1


@pytest.mark.asyncio
async def test_response_wait_timeout_respects_mark_sent_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = OneBotClient("ws://example.invalid")
    websocket = _RespondingWebSocket(client, {"status": "ok"})
    client.ws = cast(Any, websocket)
    wait_for = AsyncMock(side_effect=asyncio.TimeoutError)
    monkeypatch.setattr("Undefined.onebot.client.asyncio.wait_for", wait_for)

    async with RequestContext(
        request_type="private",
        user_id=20002,
        sender_id=20002,
    ) as request_context:
        with pytest.raises(OneBotDeliveryUncertainError):
            await client.send_private_message(
                20002,
                "background announcement",
                mark_sent=False,
            )

        assert was_message_sent(request_context) is False

    wait_for.assert_awaited_once()
    assert websocket.send_count == 1
