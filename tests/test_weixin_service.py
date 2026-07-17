from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any, cast
from unittest.mock import AsyncMock

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
    QrPollResult,
    QrStatus,
    RefMessage,
    SendReceipt,
    WeixinCredentials,
)

from Undefined.config import Config
from Undefined.attachments import AttachmentRegistry
from Undefined.utils.message_reply import ReplyContext
from Undefined.utils import io as async_io
from Undefined.weixin.audio import PreparedWeixinVoice
from Undefined.weixin.models import WeixinAccount
from Undefined.weixin.service import (
    WeixinClientProtocol,
    WeixinConfirmationRequired,
    WeixinService,
    WeixinServiceError,
)
from Undefined.weixin.store import UndefinedIlinkStateStore, WeixinStore


class FakeLoginManager:
    def __init__(self) -> None:
        self.start_calls = 0
        self.poll_calls = 0
        self.refresh_calls = 0
        self.closed = False
        self.poll_result = QrPollResult(QrStatus.WAIT, "waiting")

    async def start(self, *, local_tokens: tuple[str, ...] = ()) -> QrLoginSession:
        del local_tokens
        self.start_calls += 1
        return QrLoginSession(
            session_id=f"session-{self.start_calls}",
            qrcode=f"wire-code-{self.start_calls}",
            qrcode_url=f"https://qr.example.test/value-{self.start_calls}",
            created_at=time.time(),
            current_base_url="https://ilink.example.test",
        )

    async def poll(self, session: QrLoginSession) -> QrPollResult:
        del session
        self.poll_calls += 1
        return self.poll_result

    async def refresh(
        self,
        session: QrLoginSession,
        *,
        local_tokens: tuple[str, ...] = (),
    ) -> QrLoginSession:
        del local_tokens
        self.refresh_calls += 1
        session.qrcode = f"refreshed-wire-code-{self.refresh_calls}"
        session.qrcode_url = f"https://qr.example.test/refreshed-{self.refresh_calls}"
        session.created_at = time.time()
        session.refresh_count += 1
        return session

    async def aclose(self) -> None:
        self.closed = True


class FakeClient:
    def __init__(self) -> None:
        self.started = False
        self.closed = False
        self.sent_text: list[tuple[str, str]] = []
        self.sent_references: list[RefMessage | None] = []
        self.sent_voices: list[tuple[str, bytes, int, int, int]] = []
        self.run_started = asyncio.Event()

    async def start(self) -> None:
        self.started = True

    async def run(
        self,
        handler: Any,
        *,
        stop_event: asyncio.Event | None = None,
    ) -> None:
        del handler
        self.run_started.set()
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
        reference: RefMessage | None = None,
    ) -> SendReceipt:
        del context_token, run_id, reply_to
        self.sent_text.append((peer_id, text))
        self.sent_references.append(reference)
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
        reference: RefMessage | None = None,
    ) -> SendReceipt:
        del (
            peer_id,
            content,
            kind,
            file_name,
            caption,
            context_token,
            run_id,
            reply_to,
            reference,
        )
        return SendReceipt("client-media-1")

    async def send_voice(
        self,
        peer_id: str,
        content: bytes,
        *,
        duration_ms: int,
        sample_rate: int = 24_000,
        bits_per_sample: int = 16,
        context_token: str | None = None,
        run_id: str | None = None,
        reply_to: str | int | None = None,
        reference: RefMessage | None = None,
    ) -> SendReceipt:
        del context_token, run_id, reply_to
        self.sent_voices.append(
            (peer_id, content, duration_ms, sample_rate, bits_per_sample)
        )
        self.sent_references.append(reference)
        return SendReceipt("client-voice-1")

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


def _config(
    tmp_path: Path,
    *,
    superadmin_qq: int = 0,
    enabled: bool = True,
) -> Config:
    return Config.from_mapping(
        {
            "core": {"superadmin_qq": superadmin_qq},
            "weixin": {"enabled": enabled, "state_dir": str(tmp_path)},
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
    try:
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
    finally:
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
    try:
        await service.start()
        await asyncio.sleep(0)

        reference = RefMessage.from_text("微信用户", "quoted text")
        receipt = await service.send_text(10001, "hello", reference=reference)
        voice = PreparedWeixinVoice(
            content=b"\x02#!SILK_V3voice",
            duration_ms=250,
        )
        voice_receipt = await service.send_prepared_voice(
            10001,
            voice,
            reference=reference,
        )

        assert receipt == "client-message-1"
        assert voice_receipt == "client-voice-1"
        assert client.sent_text == [("peer-1", "hello")]
        assert client.sent_voices == [("peer-1", voice.content, 250, 24_000, 16)]
        assert client.sent_references == [reference, reference]
    finally:
        await service.stop()


@pytest.mark.asyncio
async def test_validate_media_files_rejects_oversized_file(tmp_path: Path) -> None:
    config = _config(tmp_path)
    config.weixin.media_max_size_mb = 1
    media_path = tmp_path / "large.bin"
    await async_io.write_bytes(media_path, b"x" * (1024 * 1024 + 1))
    service = WeixinService(
        config,
        login_manager=cast(QrLoginManager, FakeLoginManager()),
    )
    try:
        with pytest.raises(WeixinServiceError, match="超过大小限制"):
            await service.validate_media_files((media_path,))
    finally:
        await service.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_stage", ["start", "run"])
async def test_account_runtime_restarts_after_unhandled_failure(
    tmp_path: Path,
    failure_stage: str,
) -> None:
    config = _config(tmp_path)
    config.weixin.retry_delay_seconds = 0.01
    config.weixin.failure_backoff_seconds = 0.01
    store = WeixinStore(config.weixin)
    await store.save_account(_account())
    failed_client = FakeClient()
    if failure_stage == "start":
        failed_client.start = AsyncMock(  # type: ignore[method-assign]
            side_effect=RuntimeError("temporary start failure")
        )
    else:
        failed_client.run = AsyncMock(  # type: ignore[method-assign]
            side_effect=RuntimeError("inbound callback failure")
        )
    replacement_client = FakeClient()
    clients = [failed_client, replacement_client]

    def factory(
        account: WeixinAccount,
        state: UndefinedIlinkStateStore,
        options: ClientOptions,
    ) -> WeixinClientProtocol:
        del account, state, options
        return clients.pop(0)

    service = WeixinService(
        config,
        store=store,
        login_manager=cast(QrLoginManager, FakeLoginManager()),
        client_factory=factory,
    )
    try:
        await service.start()
        await asyncio.wait_for(replacement_client.run_started.wait(), timeout=1.0)

        status = await service.status()

        assert status["accounts"][0]["connected"] is True
        assert failed_client.closed is True
        assert clients == []
    finally:
        await service.stop()


@pytest.mark.asyncio
async def test_expired_login_session_remains_refreshable(tmp_path: Path) -> None:
    manager = FakeLoginManager()
    manager.poll_result = QrPollResult(QrStatus.EXPIRED, "QR code expired")
    service = WeixinService(
        _config(tmp_path),
        login_manager=cast(QrLoginManager, manager),
    )
    try:
        started = await service.start_login(alias="primary", qq_id=10001)

        polled = await service.poll_login(started.session_id)
        refreshed = await service.refresh_login(started.session_id)

        assert polled.status == "expired"
        assert refreshed.session_id == started.session_id
        assert refreshed.qrcode_payload == "https://qr.example.test/refreshed-1"
        assert manager.refresh_calls == 1
    finally:
        await service.stop()


@pytest.mark.asyncio
async def test_locally_expired_login_reports_expired_without_upstream_poll(
    tmp_path: Path,
) -> None:
    manager = FakeLoginManager()
    config = _config(tmp_path)
    service = WeixinService(
        config,
        login_manager=cast(QrLoginManager, manager),
    )
    try:
        started = await service.start_login(alias="primary", qq_id=10001)
        service._logins[started.session_id].session.created_at = (
            time.time() - config.weixin.login_session_ttl_seconds - 1
        )

        polled = await service.poll_login(started.session_id)
        refreshed = await service.refresh_login(started.session_id)

        assert polled.status == "expired"
        assert refreshed.session_id == started.session_id
        assert manager.poll_calls == 0
        assert manager.refresh_calls == 1
    finally:
        await service.stop()


@pytest.mark.asyncio
async def test_new_login_replaces_stale_expired_session(tmp_path: Path) -> None:
    manager = FakeLoginManager()
    config = _config(tmp_path)
    service = WeixinService(
        config,
        login_manager=cast(QrLoginManager, manager),
    )
    try:
        stale = await service.start_login(alias="primary", qq_id=10001)
        service._logins[stale.session_id].session.created_at = (
            time.time() - config.weixin.login_session_ttl_seconds - 1
        )

        replacement = await service.start_login(alias="primary", qq_id=10001)

        assert replacement.session_id == "session-2"
        assert stale.session_id not in service._logins
        assert manager.start_calls == 2
    finally:
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
    try:
        await service._handle_inbound("primary", client, message)

        assert handler.calls == []
        pending = await store.list_pending_peers()
        assert len(pending) == 1
        assert pending[0].peer_id == "unknown-peer"
        raw = (tmp_path / "bindings.json").read_text(encoding="utf-8")
        assert "secret body" not in raw
    finally:
        await service.stop()


@pytest.mark.asyncio
async def test_inbound_sdk_text_is_dispatched_without_entity_transforms(
    tmp_path: Path,
) -> None:
    literal_text = '原始 <tag> & "引号"；字面实体 &lt;tag&gt; &amp;'
    config = _config(tmp_path)
    store = WeixinStore(config.weixin)
    await store.save_account(_account())
    handler = FakeInboundHandler()
    service = WeixinService(
        config,
        store=store,
        message_handler=handler,
        login_manager=cast(QrLoginManager, FakeLoginManager()),
    )
    message = InboundMessage.from_mapping(
        "bot-account",
        {
            "seq": 2,
            "message_id": "literal-message",
            "from_user_id": "peer-1",
            "to_user_id": "bot-account",
            "client_id": "literal-client",
            "create_time_ms": 123_456,
            "session_id": "s1",
            "context_token": "ctx",
            "item_list": [
                {
                    "type": int(MessageItemType.TEXT),
                    "text_item": {"text": literal_text},
                }
            ],
        },
    )
    try:
        await service._handle_inbound("primary", FakeClient(), message)

        assert len(handler.calls) == 1
        call = handler.calls[0]
        assert call["text"] == literal_text
        assert call["message_content"] == [
            {"type": "text", "data": {"text": literal_text}}
        ]
    finally:
        await service.stop()


@pytest.mark.asyncio
async def test_inbound_text_reference_is_dispatched_as_read_only_context(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    store = WeixinStore(config.weixin)
    await store.save_account(_account())
    handler = FakeInboundHandler()
    service = WeixinService(
        config,
        store=store,
        message_handler=handler,
        login_manager=cast(QrLoginManager, FakeLoginManager()),
    )
    message = InboundMessage(
        account_id="bot-account",
        sequence=2,
        message_id="current-message",
        from_user_id="peer-1",
        to_user_id="bot-account",
        client_id="current-client",
        created_at_ms=0,
        session_id="s1",
        context_token="ctx",
        items=(
            MessageItem(
                type=MessageItemType.TEXT,
                text="能看到引用吗？",
                ref_msg=RefMessage(
                    title="微信用户",
                    message_item=MessageItem(
                        type=MessageItemType.TEXT,
                        msg_id="quoted-message",
                        text="这是被引用的正文",
                    ),
                ),
            ),
        ),
    )
    try:
        await service._handle_inbound("primary", FakeClient(), message)

        assert len(handler.calls) == 1
        call = handler.calls[0]
        assert call["text"] == "能看到引用吗？"
        assert call["message_id"] == "current-message"
        reply_context = cast(ReplyContext, call["reply_context"])
        assert reply_context.title == "微信用户"
        assert reply_context.message_id == "quoted-message"
        assert reply_context.text == "这是被引用的正文"
        assert reply_context.attachments == ()
    finally:
        await service.stop()


@pytest.mark.asyncio
async def test_inbound_reference_uses_text_when_item_type_is_missing(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    store = WeixinStore(config.weixin)
    await store.save_account(_account())
    handler = FakeInboundHandler()
    service = WeixinService(
        config,
        store=store,
        message_handler=handler,
        login_manager=cast(QrLoginManager, FakeLoginManager()),
    )
    message = InboundMessage(
        account_id="bot-account",
        sequence=3,
        message_id="current-message",
        from_user_id="peer-1",
        to_user_id="bot-account",
        client_id="current-client",
        created_at_ms=20_000,
        session_id="s1",
        context_token="ctx",
        items=(
            MessageItem(
                type=MessageItemType.TEXT,
                text="能看到引用吗？",
                ref_msg=RefMessage(
                    title="",
                    message_item=MessageItem.from_mapping(
                        {
                            "type": 0,
                            "msg_id": "quoted-message",
                            "create_time_ms": 12_500,
                            "text_item": {"text": "类型缺失但正文存在"},
                        }
                    ),
                ),
            ),
        ),
    )
    try:
        await service._handle_inbound("primary", FakeClient(), message)

        reply_context = cast(ReplyContext, handler.calls[0]["reply_context"])
        assert reply_context.message_id == "quoted-message"
        assert reply_context.text == "类型缺失但正文存在"
        assert reply_context.source_age_ms == 7_500
    finally:
        await service.stop()


@pytest.mark.asyncio
async def test_inbound_media_reference_registers_nested_attachment(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    store = WeixinStore(config.weixin)
    await store.save_account(_account())
    handler = FakeInboundHandler()
    registry = AttachmentRegistry(
        registry_path=tmp_path / "attachments.json",
        cache_dir=tmp_path / "attachments",
    )
    service = WeixinService(
        config,
        store=store,
        message_handler=handler,
        attachment_registry=registry,
        login_manager=cast(QrLoginManager, FakeLoginManager()),
    )
    message = InboundMessage(
        account_id="bot-account",
        sequence=3,
        message_id="current-media-message",
        from_user_id="peer-1",
        to_user_id="bot-account",
        client_id="current-media-client",
        created_at_ms=0,
        session_id="s1",
        context_token="ctx",
        items=(
            MessageItem(
                type=MessageItemType.TEXT,
                text="这张图呢？",
                ref_msg=RefMessage(
                    title="微信用户",
                    message_item=MessageItem(
                        type=MessageItemType.IMAGE,
                        msg_id="quoted-image",
                    ),
                ),
            ),
        ),
    )
    try:
        await service._handle_inbound("primary", FakeClient(), message)

        call = handler.calls[0]
        assert call["attachments"] == []
        reply_context = cast(ReplyContext, call["reply_context"])
        assert reply_context.text == "[图片]"
        assert len(reply_context.attachments) == 1
        assert reply_context.attachments[0]["media_type"] == "image"
        assert reply_context.attachments[0]["display_name"] == "image.png"
    finally:
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
    try:
        await service._state_store.set_cursor(
            account.credentials.account_id, "cursor-1"
        )
        await service._state_store.set_context_token(
            account.credentials.account_id,
            account.peer_id,
            "context-token",
        )

        removed = await service.remove_account("primary")

        assert removed is True
        assert await store.get_account("primary") is None
        assert (
            await service._state_store.get_cursor(account.credentials.account_id) == ""
        )
        assert (
            await service._state_store.get_context_token(
                account.credentials.account_id,
                account.peer_id,
            )
            == ""
        )
    finally:
        await service.stop()


@pytest.mark.asyncio
async def test_disabled_service_status_stays_stopped(tmp_path: Path) -> None:
    service = WeixinService(
        _config(tmp_path, enabled=False),
        login_manager=cast(QrLoginManager, FakeLoginManager()),
    )
    try:
        await service.start()

        status = await service.status()

        assert status["enabled"] is False
        assert status["running"] is False
        assert "reply_to" in status["capabilities"]["outbound"]
        assert "reply_to" not in status["capabilities"]["unsupported"]
        assert "voice" in status["capabilities"]["outbound"]
        assert "outbound_voice" not in status["capabilities"]["unsupported"]
    finally:
        await service.stop()
