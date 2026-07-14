from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any, cast

import pytest
from weixin_ilink_client import (
    ClientOptions,
    DownloadedMedia,
    InboundMessage,
    MediaKind,
    MessageItem,
    MessageItemType,
    QrLoginManager,
    QrLoginSession,
    SendReceipt,
    WeixinCredentials,
)

from Undefined.config import Config
from Undefined.weixin.models import WeixinAccount
from Undefined.weixin.service import (
    WeixinClientProtocol,
    WeixinConfirmationRequired,
    WeixinService,
)
from Undefined.weixin.store import UndefinedIlinkStateStore, WeixinStore


class FakeLoginManager:
    def __init__(self) -> None:
        self.start_calls = 0
        self.closed = False

    async def start(self, *, local_tokens: tuple[str, ...] = ()) -> QrLoginSession:
        del local_tokens
        self.start_calls += 1
        return QrLoginSession(
            session_id="session-1",
            qrcode="wire-code",
            qrcode_url="https://qr.example.test/value",
            created_at=time.time(),
            current_base_url="https://ilink.example.test",
        )

    async def aclose(self) -> None:
        self.closed = True


class FakeClient:
    def __init__(self) -> None:
        self.started = False
        self.closed = False
        self.sent_text: list[tuple[str, str]] = []

    async def start(self) -> None:
        self.started = True

    async def run(
        self,
        handler: Any,
        *,
        stop_event: asyncio.Event | None = None,
    ) -> None:
        del handler
        if stop_event is not None:
            await stop_event.wait()

    async def send_text(
        self,
        peer_id: str,
        text: str,
        *,
        context_token: str | None = None,
        run_id: str | None = None,
        reply_to: str | int | None = None,
    ) -> SendReceipt:
        del context_token, run_id, reply_to
        self.sent_text.append((peer_id, text))
        return SendReceipt("client-message-1")

    async def send_media(
        self,
        peer_id: str,
        content: bytes,
        *,
        kind: MediaKind,
        file_name: str,
        caption: str = "",
        context_token: str | None = None,
        run_id: str | None = None,
        reply_to: str | int | None = None,
    ) -> SendReceipt:
        del peer_id, content, kind, file_name, caption, context_token, run_id, reply_to
        return SendReceipt("client-media-1")

    async def download_media(self, item: MessageItem) -> DownloadedMedia:
        del item
        return DownloadedMedia(
            kind=MediaKind.IMAGE,
            content=b"image",
            content_type="image/png",
            file_name="image.png",
        )

    async def set_typing(
        self,
        peer_id: str,
        typing: bool,
        *,
        context_token: str | None = None,
    ) -> None:
        del peer_id, typing, context_token

    async def aclose(self) -> None:
        self.closed = True


class FakeInboundHandler:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def handle_weixin_private_message(self, **kwargs: Any) -> None:
        self.calls.append(kwargs)


def _config(tmp_path: Path, *, superadmin_qq: int = 0) -> Config:
    return Config.from_mapping(
        {
            "core": {"superadmin_qq": superadmin_qq},
            "weixin": {"enabled": True, "state_dir": str(tmp_path)},
        },
        strict=False,
    )


def _account() -> WeixinAccount:
    return WeixinAccount(
        alias="primary",
        qq_id=10001,
        credentials=WeixinCredentials(
            "bot-account", "secret", "https://ilink.example.test", "peer-1"
        ),
        enabled=True,
        created_at="2026-01-01T00:00:00+08:00",
        updated_at="2026-01-01T00:00:00+08:00",
    )


@pytest.mark.asyncio
async def test_privileged_binding_requires_confirmation_before_network(
    tmp_path: Path,
) -> None:
    manager = FakeLoginManager()
    service = WeixinService(
        _config(tmp_path, superadmin_qq=4242),
        login_manager=cast(QrLoginManager, manager),
    )

    with pytest.raises(WeixinConfirmationRequired) as raised:
        await service.start_login(alias="admin", qq_id=4242)
    assert manager.start_calls == 0

    result = await service.start_login(
        alias="admin",
        qq_id=4242,
        confirmation_token=raised.value.token,
    )
    assert result.session_id == "session-1"
    assert manager.start_calls == 1
    await service.stop()


@pytest.mark.asyncio
async def test_account_runtime_sends_by_logical_qq(tmp_path: Path) -> None:
    config = _config(tmp_path)
    store = WeixinStore(config.weixin)
    await store.save_account(_account())
    client = FakeClient()

    def factory(
        account: WeixinAccount,
        state: UndefinedIlinkStateStore,
        options: ClientOptions,
    ) -> WeixinClientProtocol:
        del account, state, options
        return client

    service = WeixinService(
        config,
        store=store,
        login_manager=cast(QrLoginManager, FakeLoginManager()),
        client_factory=factory,
    )
    await service.start()
    await asyncio.sleep(0)

    receipt = await service.send_text(10001, "hello")

    assert receipt == "client-message-1"
    assert client.sent_text == [("peer-1", "hello")]
    await service.stop()


@pytest.mark.asyncio
async def test_unknown_peer_is_quarantined_without_dispatch(tmp_path: Path) -> None:
    config = _config(tmp_path)
    store = WeixinStore(config.weixin)
    await store.save_account(_account())
    handler = FakeInboundHandler()
    client = FakeClient()
    service = WeixinService(
        config,
        store=store,
        message_handler=handler,
        login_manager=cast(QrLoginManager, FakeLoginManager()),
    )
    message = InboundMessage(
        account_id="bot-account",
        sequence=1,
        message_id="m1",
        from_user_id="unknown-peer",
        to_user_id="bot-account",
        client_id="c1",
        created_at_ms=0,
        session_id="s1",
        context_token="ctx",
        items=(MessageItem(type=MessageItemType.TEXT, text="secret body"),),
    )

    await service._handle_inbound("primary", client, message)

    assert handler.calls == []
    pending = await store.list_pending_peers()
    assert len(pending) == 1
    assert pending[0].peer_id == "unknown-peer"
    raw = (tmp_path / "bindings.json").read_text(encoding="utf-8")
    assert "secret body" not in raw
    await service.stop()


@pytest.mark.asyncio
async def test_remove_account_purges_sdk_runtime_state(tmp_path: Path) -> None:
    config = _config(tmp_path)
    store = WeixinStore(config.weixin)
    account = _account()
    await store.save_account(account)
    service = WeixinService(
        config,
        store=store,
        login_manager=cast(QrLoginManager, FakeLoginManager()),
    )
    await service._state_store.set_cursor(account.credentials.account_id, "cursor-1")
    await service._state_store.set_context_token(
        account.credentials.account_id,
        account.peer_id,
        "context-token",
    )

    removed = await service.remove_account("primary")

    assert removed is True
    assert await store.get_account("primary") is None
    assert await service._state_store.get_cursor(account.credentials.account_id) == ""
    assert (
        await service._state_store.get_context_token(
            account.credentials.account_id,
            account.peer_id,
        )
        == ""
    )
    await service.stop()
