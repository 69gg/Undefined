from __future__ import annotations

import json
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from weixin_ilink_client import (
    ApiError,
    AsyncWeixinIlinkClient,
    ClientOptions,
    ConfigurationError,
    HttpError,
    MediaKind,
    OutboundMediaItem,
    RequestTimeoutError,
    SessionPausedError,
    TransportError,
    WeixinCredentials,
)
from weixin_ilink_client.constants import STALE_TOKEN_ERROR_CODE

from Undefined.config import Config
from Undefined.jm.sender import _send_result
from Undefined.utils.message_targets import DeliveryAddress
from Undefined.utils.sender import MAX_MESSAGE_LENGTH, AddressBoundSender, MessageSender
from Undefined.weixin.models import WeixinAccount
from Undefined.weixin.service import WeixinService
from Undefined.weixin.store import UndefinedIlinkStateStore
from Undefined.weixin.transport import (
    UndefinedIlinkTransport,
    WeixinDeliveryUncertainError,
    is_definitive_weixin_delivery_rejection,
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        "timeout",
        "connect_error",
        "connect_timeout",
        "pool_timeout",
        "server_error",
        "rejection",
        "history_error",
        "partial_bundle_rejection",
        "partial_sequential_rejection",
        "partial_fallback_rejection",
        "partial_connect_failure",
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
        if response == "partial_connect_failure":
            if len(requests) == 2:
                raise httpx.ConnectError("second batch was not sent", request=request)
            return httpx.Response(200, json={"ret": 0}, request=request)
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
            connection_failure = {
                "connect_error": httpx.ConnectError,
                "connect_timeout": httpx.ConnectTimeout,
                "pool_timeout": httpx.PoolTimeout,
            }.get(response)
            if connection_failure is not None:
                raise connection_failure("request was not sent", request=request)
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
        1 if response in {"partial_bundle_rejection", "partial_connect_failure"} else 10
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
        assert len(requests) == (
            2
            if response in {"partial_sequential_rejection", "partial_connect_failure"}
            else 3
        )
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
    elif response in {"connect_error", "connect_timeout", "pool_timeout"}:
        assert [len(message["item_list"]) for message in requests] == [2, 1, 1]
        assert "合并转发被拒，已改为普通消息发送信息与密码" in status
    else:
        assert len(requests) == 1
        assert len(requests[0]["item_list"]) == 2
        assert "投递结果未确认" in status


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [400, 408, 425, 429, 503])
async def test_sdk_http_rejection_preserves_delivery_classification(
    status_code: int,
) -> None:
    requests: list[httpx.Request] = []

    def reject(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(status_code, request=request)

    credentials = WeixinCredentials(
        "account", "token", "https://isolated.invalid", "user"
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(reject)) as http_client:
        client = AsyncWeixinIlinkClient(
            credentials,
            transport=UndefinedIlinkTransport(http_client=http_client),
        )
        error_type = WeixinDeliveryUncertainError if status_code == 503 else HttpError
        with pytest.raises(error_type) as raised:
            await client.send_text("peer", "message")

    assert len(requests) == 1
    assert bool(getattr(raised.value, "delivery_uncertain", False)) is (
        status_code == 503
    )
    assert is_definitive_weixin_delivery_rejection(raised.value) is (status_code == 400)
    http_error = raised.value.__cause__ if status_code == 503 else raised.value
    assert isinstance(http_error, HttpError)
    assert http_error.status_code == status_code


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [408, 425, 429, 503])
@pytest.mark.parametrize("partial", [False, True])
async def test_sdk_http_rejection_blocks_reply_fallback_and_partial_resend(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    status_code: int,
    partial: bool,
) -> None:
    requests: list[dict[str, Any]] = []

    def reject(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content)["msg"])
        if partial and len(requests) == 1:
            return httpx.Response(200, json={"ret": 0}, request=request)
        return httpx.Response(status_code, request=request)

    config = Config.from_mapping(
        {"weixin": {"enabled": True, "state_dir": str(tmp_path)}}, strict=False
    )
    service = WeixinService(config)
    history = MagicMock()
    history.find_private_message_by_id = AsyncMock(
        return_value={
            "message_id": "inbound-1",
            "display_name": "微信用户",
            "message": "旧消息",
            "transport": {"channel": "wechat", "address": "wechat:12345"},
        }
    )
    sender = MessageSender(MagicMock(), history, bot_qq=999, config=MagicMock())
    sender.set_weixin_service(service)
    credentials = WeixinCredentials(
        "account", "token", "https://isolated.invalid", "user"
    )
    message = "x" * (MAX_MESSAGE_LENGTH + 1) if partial else "message"
    try:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(reject)
        ) as http_client:
            client = AsyncWeixinIlinkClient(
                credentials,
                transport=UndefinedIlinkTransport(http_client=http_client),
            )
            monkeypatch.setattr(
                service,
                "_resolve_runtime",
                AsyncMock(
                    return_value=(
                        SimpleNamespace(peer_id="peer"),
                        SimpleNamespace(client=client),
                    )
                ),
            )
            uncertain = partial or status_code == 503
            error_type = WeixinDeliveryUncertainError if uncertain else HttpError
            with pytest.raises(error_type) as raised:
                await sender.send_address_message(
                    DeliveryAddress("wechat", 12345),
                    message,
                    auto_history=False,
                    reply_to="inbound-1",
                )
        assert bool(getattr(raised.value, "delivery_uncertain", False)) is uncertain
        assert len(requests) == (2 if partial else 1)
        if partial and status_code != 503:
            assert isinstance(raised.value.__cause__, HttpError)
            assert raised.value.__cause__.status_code == status_code
    finally:
        await service.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error_type",
    [
        httpx.ReadTimeout,
        httpx.WriteTimeout,
        httpx.ReadError,
        httpx.WriteError,
        httpx.RemoteProtocolError,
    ],
)
async def test_dispatch_failure_preserves_uncertain_sdk_cause(
    error_type: type[httpx.RequestError],
) -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise error_type("request or response interrupted", request=request)

    credentials = WeixinCredentials(
        "account", "token", "https://isolated.invalid", "user"
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(timeout)) as client:
        transport = UndefinedIlinkTransport(http_client=client)
        with pytest.raises(WeixinDeliveryUncertainError) as raised:
            await transport.send_message(credentials, {"item_list": []})
    assert raised.value.delivery_uncertain is True
    assert isinstance(raised.value.__cause__, TransportError)
    assert isinstance(raised.value.__cause__.__cause__, error_type)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error_type", [httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout]
)
async def test_pre_dispatch_failure_preserves_sdk_error(
    error_type: type[httpx.RequestError],
) -> None:
    def fail_before_send(request: httpx.Request) -> httpx.Response:
        raise error_type("request was not sent", request=request)

    credentials = WeixinCredentials(
        "account", "token", "https://isolated.invalid", "user"
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(fail_before_send)
    ) as http_client:
        client = AsyncWeixinIlinkClient(
            credentials,
            transport=UndefinedIlinkTransport(http_client=http_client),
        )
        with pytest.raises(TransportError) as raised:
            await client.send_text("peer", "message")
    assert not getattr(raised.value, "delivery_uncertain", False)
    assert isinstance(raised.value.__cause__, error_type)


@pytest.mark.asyncio
@pytest.mark.parametrize("paused", [False, True])
@pytest.mark.parametrize("through_sender", [False, True])
async def test_authentication_rejection_reaches_service_without_uncertain_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    paused: bool,
    through_sender: bool,
) -> None:
    requests: list[str] = []

    def reject_token(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        return httpx.Response(200, json={"ret": STALE_TOKEN_ERROR_CODE})

    credentials = WeixinCredentials(
        "account", "token", "https://isolated.invalid", "user"
    )
    config = Config.from_mapping(
        {"weixin": {"enabled": True, "state_dir": str(tmp_path)}}, strict=False
    )
    service = WeixinService(config)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(reject_token)
    ) as http_client:
        client = AsyncWeixinIlinkClient(
            credentials,
            transport=UndefinedIlinkTransport(http_client=http_client),
        )
        if paused:
            await client.state_store.set_pause_until(
                credentials.account_id, time.time() + 60
            )
        monkeypatch.setattr(
            service,
            "_resolve_runtime",
            AsyncMock(
                return_value=(
                    SimpleNamespace(peer_id="peer"),
                    SimpleNamespace(client=client),
                )
            ),
        )
        with pytest.raises(ApiError) as raised:
            if through_sender:
                sender_config = MagicMock()
                sender_config.weixin.multi_item_messages_enabled = True
                sender_config.weixin.multi_item_max_items = 10
                sender_config.weixin.media_max_size_mb = 100
                sender = MessageSender(
                    MagicMock(), MagicMock(), bot_qq=999, config=sender_config
                )
                sender.set_weixin_service(service)
                bound = AddressBoundSender(sender, DeliveryAddress("wechat", 12345))
                await bound.send_private_forward_message(
                    12345,
                    [{"type": "node", "data": {"name": "Bot", "content": "报告"}}],
                    history_message="报告",
                    auto_history=False,
                )
            else:
                await service.send_text(12345, "message")
    await service.stop()
    assert raised.value.code == STALE_TOKEN_ERROR_CODE
    assert not getattr(raised.value, "delivery_uncertain", False)
    # 认证过期不能靠移除引用或拆分多项消息解决，仍不属于结构降级候选。
    assert not is_definitive_weixin_delivery_rejection(raised.value)
    if paused:
        assert isinstance(raised.value, SessionPausedError)
        assert requests == []
    else:
        assert requests == ["/ilink/bot/sendmessage"]


@pytest.mark.asyncio
async def test_invalid_dispatch_url_is_known_not_sent() -> None:
    def unexpected_request(request: httpx.Request) -> httpx.Response:
        pytest.fail("invalid dispatch URL must not produce an HTTP request")

    credentials = WeixinCredentials("account", "token", "http://invalid", "user")
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(unexpected_request)
    ) as http_client:
        transport = UndefinedIlinkTransport(http_client=http_client)
        with pytest.raises(ConfigurationError) as raised:
            await transport.send_message(credentials, {"item_list": []})
    assert not getattr(raised.value, "delivery_uncertain", False)


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
