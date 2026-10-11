from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from weixin_ilink_client import (
    AsyncWeixinIlinkClient,
    ClientOptions,
    MediaKind,
    OutboundMediaItem,
    RequestTimeoutError,
    WeixinCredentials,
)

from Undefined.config import Config
from Undefined.jm.sender import _send_result
from Undefined.utils.message_targets import DeliveryAddress
from Undefined.utils.sender import AddressBoundSender, MessageSender
from Undefined.weixin.models import WeixinAccount
from Undefined.weixin.service import WeixinService
from Undefined.weixin.store import UndefinedIlinkStateStore
from Undefined.weixin.transport import (
    UndefinedIlinkTransport,
    WeixinDeliveryUncertainError,
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        "timeout",
        "server_error",
        "rejection",
        "history_error",
        "partial_bundle_rejection",
        "partial_sequential_rejection",
        "partial_fallback_rejection",
        "first_sequential_rejection",
    ],
)
async def test_sdk_dispatch_error_controls_jm_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    response: str,
) -> None:
    requests: list[dict[str, Any]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        message = json.loads(request.content)["msg"]
        requests.append(message)
        rejected_requests = {
            "partial_bundle_rejection": {2, 3},
            "partial_sequential_rejection": {2},
            "partial_fallback_rejection": {1, 3},
            "first_sequential_rejection": {1},
        }.get(response)
        if rejected_requests is not None:
            return httpx.Response(
                200,
                json={"ret": 40001 if len(requests) in rejected_requests else 0},
                request=request,
            )
        if len(requests) == 1:
            if response == "history_error":
                return httpx.Response(200, json={"ret": 0}, request=request)
            if response == "timeout":
                raise httpx.ReadTimeout("response lost after POST", request=request)
            if response == "server_error":
                return httpx.Response(503, request=request)
            return httpx.Response(200, json={"ret": 40001}, request=request)
        return httpx.Response(200, json={"ret": 0}, request=request)

    config = Config.from_mapping(
        {"weixin": {"enabled": True, "state_dir": str(tmp_path)}}, strict=False
    )
    service = WeixinService(config)
    credentials = WeixinCredentials(
        "isolated-account",
        "isolated-token",
        "https://isolated.invalid",
        "isolated-user",
    )
    history = MagicMock()
    history.add_private_message = AsyncMock()
    if response == "history_error":
        history.add_private_message.side_effect = [
            OSError("isolated history write failure after ACK"),
            None,
            None,
            None,
        ]
    sender_config = MagicMock()
    sender_config.is_private_allowed.return_value = True
    sender_config.weixin.multi_item_messages_enabled = response not in {
        "partial_sequential_rejection",
        "first_sequential_rejection",
    }
    sender_config.weixin.multi_item_max_items = (
        1 if response == "partial_bundle_rejection" else 10
    )
    sender_config.weixin.media_max_size_mb = 100
    sender = MessageSender(MagicMock(), history, bot_qq=999, config=sender_config)
    sender.set_weixin_service(service)
    zip_send = AsyncMock(return_value="zip-ack")
    monkeypatch.setattr(service, "send_file", zip_send)
    source = tmp_path / "report.zip"
    source.write_bytes(b"isolated zip")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http_client:
        client = AsyncWeixinIlinkClient(
            credentials,
            transport=UndefinedIlinkTransport(http_client=http_client),
        )
        monkeypatch.setattr(
            service,
            "_resolve_runtime",
            AsyncMock(
                return_value=(
                    SimpleNamespace(peer_id="isolated-peer"),
                    SimpleNamespace(client=client),
                )
            ),
        )
        status = await _send_result(
            cast(
                MessageSender,
                AddressBoundSender(sender, DeliveryAddress("wechat", 12345)),
            ),
            "private",
            12345,
            book_id="123456",
            info_text="book info",
            password="isolated-password",
            zip_path=source,
            history_message="book info",
        )
    zip_send.assert_awaited_once()
    await service.stop()
    if response.startswith("partial_"):
        assert len(requests) == (2 if response == "partial_sequential_rejection" else 3)
        assert "投递结果未确认" in status
    elif response == "first_sequential_rejection":
        assert [len(message["item_list"]) for message in requests] == [1, 1, 1]
        assert "合并转发被拒，已改为普通消息发送信息与密码" in status
    elif response == "history_error":
        assert [len(message["item_list"]) for message in requests] == [2]
        assert "已发送合并转发" in status
    elif response == "rejection":
        assert [len(message["item_list"]) for message in requests] == [2, 1, 1]
        assert "已发送合并转发" in status
    else:
        assert len(requests) == 1
        assert len(requests[0]["item_list"]) == 2
        assert "投递结果未确认" in status


@pytest.mark.asyncio
async def test_dispatch_timeout_preserves_sdk_cause() -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("response lost", request=request)

    credentials = WeixinCredentials(
        "account", "token", "https://isolated.invalid", "user"
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(timeout)) as client:
        transport = UndefinedIlinkTransport(http_client=client)
        with pytest.raises(WeixinDeliveryUncertainError) as raised:
            await transport.send_message(credentials, {"item_list": []})
    assert raised.value.delivery_uncertain is True
    assert isinstance(raised.value.__cause__, RequestTimeoutError)
    assert isinstance(raised.value.__cause__.__cause__, httpx.ReadTimeout)


@pytest.mark.asyncio
async def test_sdk_media_preparation_failure_is_not_dispatched() -> None:
    paths: list[str] = []

    def timeout(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        raise httpx.ReadTimeout("upload preparation failed", request=request)

    credentials = WeixinCredentials(
        "account", "token", "https://isolated.invalid", "user"
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(timeout)) as http_client:
        client = AsyncWeixinIlinkClient(
            credentials,
            transport=UndefinedIlinkTransport(http_client=http_client),
            options=ClientOptions(media_upload_attempts=1),
        )
        with pytest.raises(RequestTimeoutError) as raised:
            await client.send_items(
                "peer", [OutboundMediaItem(MediaKind.FILE, b"file", "report.txt")]
            )
    assert not getattr(raised.value, "delivery_uncertain", False)
    assert paths == ["/ilink/bot/getuploadurl"]


@pytest.mark.asyncio
async def test_production_client_uses_dispatch_adapter(tmp_path: Path) -> None:
    config = Config.from_mapping(
        {"weixin": {"enabled": True, "state_dir": str(tmp_path)}}, strict=False
    )
    service = WeixinService(config)
    account = WeixinAccount(
        alias="isolated",
        qq_id=12345,
        credentials=WeixinCredentials(
            "account", "token", "https://isolated.invalid", "user"
        ),
        enabled=True,
        created_at="",
        updated_at="",
    )
    client = cast(
        AsyncWeixinIlinkClient,
        service._build_client(
            account,
            UndefinedIlinkStateStore(tmp_path / "runtime.json"),
            ClientOptions(),
        ),
    )
    assert isinstance(client.transport, UndefinedIlinkTransport)
    await client.aclose()
    await service.stop()
