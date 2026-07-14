"""微信 iLink 帐号生命周期、登录和消息桥接服务。"""

from __future__ import annotations

import asyncio
import logging
import mimetypes
import secrets
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from weixin_ilink_client import (
    AsyncWeixinIlinkClient,
    ClientOptions,
    DownloadedMedia,
    IlinkTransport,
    InboundMessage,
    MediaKind,
    MessageItem,
    MessageItemType,
    QrLoginManager,
    QrLoginSession,
    QrPollResult,
    SendReceipt,
    WeixinIlinkError,
)

from Undefined import __version__
from Undefined.attachments.registry import AttachmentRegistry
from Undefined.config import Config
from Undefined.utils import io
from Undefined.utils.logging import redact_string
from Undefined.weixin.models import WeixinAccount, normalize_alias
from Undefined.weixin.store import UndefinedIlinkStateStore, WeixinStore

logger = logging.getLogger(__name__)


class WeixinServiceError(RuntimeError):
    """可安全展示给管理端的微信服务错误。"""


class WeixinNotFoundError(WeixinServiceError):
    pass


class WeixinConflictError(WeixinServiceError):
    pass


class WeixinUpstreamError(WeixinServiceError):
    """微信 iLink 上游请求失败。"""


class WeixinConfirmationRequired(WeixinServiceError):
    """管理员身份绑定需要二次确认。"""

    def __init__(self, token: str, warning: str, expires_at: float) -> None:
        super().__init__(warning)
        self.token = token
        self.warning = warning
        self.expires_at = expires_at


class WeixinInboundHandler(Protocol):
    async def handle_weixin_private_message(
        self,
        *,
        qq_id: int,
        text: str,
        message_content: list[dict[str, Any]],
        attachments: list[dict[str, str]],
        sender_name: str,
        message_id: str | None,
        account_alias: str,
    ) -> None: ...


class WeixinClientProtocol(Protocol):
    async def start(self) -> None: ...

    async def run(
        self,
        handler: Callable[[InboundMessage], Awaitable[None]],
        *,
        stop_event: asyncio.Event | None = None,
    ) -> None: ...

    async def send_text(
        self,
        peer_id: str,
        text: str,
        *,
        context_token: str | None = None,
        run_id: str | None = None,
        reply_to: str | int | None = None,
    ) -> SendReceipt: ...

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
    ) -> SendReceipt: ...

    async def download_media(self, item: MessageItem) -> DownloadedMedia: ...

    async def set_typing(
        self,
        peer_id: str,
        typing: bool,
        *,
        context_token: str | None = None,
    ) -> None: ...

    async def aclose(self) -> None: ...


ClientFactory = Callable[
    [WeixinAccount, UndefinedIlinkStateStore, ClientOptions], WeixinClientProtocol
]


@dataclass(frozen=True, slots=True)
class LoginStartResult:
    session_id: str
    qrcode_payload: str
    expires_at: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "qrcode_payload": self.qrcode_payload,
            "expires_at": self.expires_at,
        }


@dataclass(frozen=True, slots=True)
class LoginPollView:
    session_id: str
    status: str
    message: str
    account: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "session_id": self.session_id,
            "status": self.status,
            "message": self.message,
        }
        if self.account is not None:
            result["account"] = dict(self.account)
        return result


@dataclass(slots=True)
class _PendingLogin:
    alias: str
    qq_id: int
    session: QrLoginSession


@dataclass(frozen=True, slots=True)
class _Confirmation:
    operation: str
    alias: str
    qq_id: int
    expires_at: float


@dataclass(slots=True)
class _AccountRuntime:
    client: WeixinClientProtocol
    stop_event: asyncio.Event
    task: asyncio.Task[None]
    connected: bool = False
    last_error: str = ""


class WeixinService:
    """将 iLink 私聊映射到 Undefined 的逻辑 QQ 私聊。"""

    def __init__(
        self,
        config: Config,
        *,
        message_handler: WeixinInboundHandler | None = None,
        attachment_registry: AttachmentRegistry | None = None,
        store: WeixinStore | None = None,
        login_manager: QrLoginManager | None = None,
        client_factory: ClientFactory | None = None,
    ) -> None:
        self.config = config
        self.weixin_config = config.weixin
        self.message_handler = message_handler
        self.attachment_registry = attachment_registry
        self.store = store or WeixinStore(config.weixin)
        self._bot_agent = f"Undefined/{__version__}"
        self._login_manager = login_manager or QrLoginManager(
            transport=IlinkTransport(bot_agent=self._bot_agent),
            session_ttl_seconds=config.weixin.login_session_ttl_seconds,
        )
        self._client_factory = client_factory or self._build_client
        self._state_store = UndefinedIlinkStateStore(
            Path(config.weixin.state_dir).expanduser() / "runtime.json"
        )
        self._logins: dict[str, _PendingLogin] = {}
        self._confirmations: dict[str, _Confirmation] = {}
        self._runtimes: dict[str, _AccountRuntime] = {}
        self._login_lock = asyncio.Lock()
        self._lifecycle_lock = asyncio.Lock()
        self._running = False
        self._closed = False

    def _build_client(
        self,
        account: WeixinAccount,
        state_store: UndefinedIlinkStateStore,
        options: ClientOptions,
    ) -> WeixinClientProtocol:
        transport = IlinkTransport(bot_agent=self._bot_agent)
        return AsyncWeixinIlinkClient(
            account.credentials,
            transport=transport,
            state_store=state_store,
            options=options,
        )

    def _client_options(self) -> ClientOptions:
        cfg = self.weixin_config
        return ClientOptions(
            long_poll_timeout_seconds=cfg.long_poll_timeout_seconds,
            stale_token_pause_seconds=cfg.stale_token_pause_seconds,
            retry_delay_seconds=cfg.retry_delay_seconds,
            failure_backoff_seconds=cfg.failure_backoff_seconds,
            failures_before_backoff=cfg.failures_before_backoff,
            media_max_bytes=cfg.media_max_size_mb * 1024 * 1024,
        )

    async def start(self) -> None:
        """启动所有已启用帐号；未启用配置时保持完全离线。"""
        async with self._lifecycle_lock:
            if self._running:
                return
            if self._closed:
                raise RuntimeError("WeixinService 已关闭")
            if not self.weixin_config.enabled:
                logger.info("[微信] iLink 接入未启用")
                return
            self._running = True
            for account in await self.store.list_accounts():
                if account.enabled:
                    await self._start_account_locked(account)

    async def stop(self) -> None:
        async with self._lifecycle_lock:
            if self._closed:
                return
            aliases = list(self._runtimes)
            for alias in aliases:
                await self._stop_account_locked(alias)
            await self._login_manager.aclose()
            self._logins.clear()
            self._confirmations.clear()
            self._running = False
            self._closed = True

    async def status(self) -> dict[str, Any]:
        accounts = await self.store.list_accounts()
        return {
            "enabled": self.weixin_config.enabled,
            "running": self.weixin_config.enabled and self._running,
            "accounts": [
                account.to_public_dict(
                    connected=(runtime.connected if runtime else False),
                    error=(runtime.last_error if runtime else ""),
                )
                for account in accounts
                for runtime in [self._runtimes.get(account.alias)]
            ],
            "active_login_sessions": len(self._logins),
            "capabilities": {
                "inbound": ["text", "image", "file", "video", "voice"],
                "outbound": ["text", "image", "file", "video", "typing"],
                "unsupported": ["outbound_voice", "reply_to"],
            },
        }

    async def start_login(
        self,
        *,
        alias: str,
        qq_id: int,
        confirmation_token: str | None = None,
        actor: str = "management-api",
    ) -> LoginStartResult:
        self._ensure_available()
        async with self._login_lock:
            normalized_alias = self._normalize_alias(alias)
            self._validate_qq_id(qq_id)
            if await self.store.get_account(normalized_alias) is not None:
                raise WeixinConflictError(f"帐号别名 {normalized_alias} 已存在")
            conflict = await self.store.get_by_qq(qq_id)
            if conflict is not None:
                raise WeixinConflictError(f"QQ {qq_id} 已绑定帐号 {conflict.alias}")
            pending_conflict = next(
                (
                    pending
                    for pending in self._logins.values()
                    if pending.alias == normalized_alias or pending.qq_id == qq_id
                ),
                None,
            )
            if pending_conflict is not None:
                raise WeixinConflictError("该帐号别名或逻辑 QQ 已有登录会话")
            await self._require_privileged_confirmation(
                operation="bind",
                alias=normalized_alias,
                qq_id=qq_id,
                confirmation_token=confirmation_token,
                actor=actor,
            )
            try:
                session = await self._login_manager.start(
                    local_tokens=await self.store.local_tokens()
                )
            except WeixinIlinkError as exc:
                raise WeixinUpstreamError(self._safe_upstream_error(exc)) from exc
            self._logins[session.session_id] = _PendingLogin(
                alias=normalized_alias,
                qq_id=qq_id,
                session=session,
            )
            await self.store.append_audit(
                "login_started",
                actor=actor,
                details={"alias": normalized_alias, "qq_id": qq_id},
            )
            return LoginStartResult(
                session_id=session.session_id,
                qrcode_payload=session.qrcode_url,
                expires_at=session.created_at
                + self.weixin_config.login_session_ttl_seconds,
            )

    async def poll_login(
        self,
        session_id: str,
        *,
        actor: str = "management-api",
    ) -> LoginPollView:
        async with self._login_lock:
            pending = self._get_login(session_id)
            try:
                result = await self._login_manager.poll(pending.session)
            except WeixinIlinkError as exc:
                raise WeixinUpstreamError(self._safe_upstream_error(exc)) from exc
            if result.credentials is None:
                if result.status.value in {"expired", "binded_redirect"}:
                    self._logins.pop(session_id, None)
                return LoginPollView(
                    session_id=session_id,
                    status=result.status.value,
                    message=result.message,
                )
            account = await self._complete_login(pending, result, actor=actor)
            self._logins.pop(session_id, None)
            return LoginPollView(
                session_id=session_id,
                status=result.status.value,
                message=result.message,
                account=account.to_public_dict(connected=False),
            )

    async def refresh_login(self, session_id: str) -> LoginStartResult:
        self._ensure_available()
        async with self._login_lock:
            pending = self._get_login(session_id)
            try:
                await self._login_manager.refresh(
                    pending.session,
                    local_tokens=await self.store.local_tokens(),
                )
            except WeixinIlinkError as exc:
                raise WeixinUpstreamError(self._safe_upstream_error(exc)) from exc
            return LoginStartResult(
                session_id=session_id,
                qrcode_payload=pending.session.qrcode_url,
                expires_at=pending.session.created_at
                + self.weixin_config.login_session_ttl_seconds,
            )

    async def submit_verify_code(self, session_id: str, code: str) -> None:
        self._ensure_available()
        async with self._login_lock:
            pending = self._get_login(session_id)
            try:
                self._login_manager.submit_verify_code(pending.session, code)
            except WeixinIlinkError as exc:
                raise WeixinUpstreamError(self._safe_upstream_error(exc)) from exc

    async def cancel_login(self, session_id: str) -> bool:
        async with self._login_lock:
            return self._logins.pop(str(session_id).strip(), None) is not None

    def get_login_qrcode_payload(self, session_id: str) -> str:
        """返回临时扫码载荷；不包含帐号 token。"""
        return self._get_login(session_id).session.qrcode_url

    async def set_account_enabled(
        self,
        alias: str,
        enabled: bool,
        *,
        actor: str = "management-api",
    ) -> dict[str, Any]:
        try:
            account = await self.store.set_account_enabled(alias, enabled)
        except KeyError as exc:
            raise WeixinNotFoundError(f"帐号 {alias} 不存在") from exc
        except ValueError as exc:
            raise WeixinServiceError(str(exc)) from exc
        async with self._lifecycle_lock:
            if enabled and self._running and self.weixin_config.enabled:
                await self._start_account_locked(account)
            elif not enabled:
                await self._stop_account_locked(account.alias)
        await self.store.append_audit(
            "account_enabled" if enabled else "account_disabled",
            actor=actor,
            details={"alias": account.alias, "qq_id": account.qq_id},
        )
        runtime = self._runtimes.get(account.alias)
        return account.to_public_dict(
            connected=runtime.connected if runtime else False,
            error=runtime.last_error if runtime else "",
        )

    async def remove_account(
        self,
        alias: str,
        *,
        actor: str = "management-api",
    ) -> bool:
        normalized = self._normalize_alias(alias)
        async with self._lifecycle_lock:
            await self._stop_account_locked(normalized)
            existing = await self.store.get_account(normalized)
            if existing is None:
                return False
            await self._state_store.delete_account(existing.credentials.account_id)
            account = await self.store.remove_account(normalized)
        if account is None:
            return False
        await self.store.append_audit(
            "account_removed",
            actor=actor,
            details={"alias": account.alias, "qq_id": account.qq_id},
        )
        return True

    async def rebind_account(
        self,
        alias: str,
        qq_id: int,
        *,
        confirmation_token: str | None = None,
        actor: str = "management-api",
    ) -> dict[str, Any]:
        normalized = self._normalize_alias(alias)
        self._validate_qq_id(qq_id)
        existing = await self.store.get_account(normalized)
        if existing is None:
            raise WeixinNotFoundError(f"帐号 {normalized} 不存在")
        await self._require_privileged_confirmation(
            operation="rebind",
            alias=normalized,
            qq_id=qq_id,
            confirmation_token=confirmation_token,
            actor=actor,
        )
        try:
            updated = await self.store.rebind_account(normalized, qq_id)
        except ValueError as exc:
            raise WeixinConflictError(str(exc)) from exc
        await self.store.append_audit(
            "account_rebound",
            actor=actor,
            details={
                "alias": normalized,
                "old_qq_id": existing.qq_id,
                "qq_id": qq_id,
            },
        )
        runtime = self._runtimes.get(normalized)
        return updated.to_public_dict(
            connected=runtime.connected if runtime else False,
            error=runtime.last_error if runtime else "",
        )

    async def send_text(
        self,
        qq_id: int,
        text: str,
        *,
        reply_to: str | int | None = None,
    ) -> str:
        account, runtime = await self._resolve_runtime(qq_id)
        receipt = await runtime.client.send_text(
            account.peer_id,
            text,
            reply_to=reply_to,
        )
        return receipt.client_id

    async def send_file(
        self,
        qq_id: int,
        file_path: str | Path,
        *,
        name: str | None = None,
        kind: MediaKind | str | None = None,
        caption: str = "",
    ) -> str:
        path = Path(file_path).expanduser()
        resolved_name = (Path(name).name if name else "") or path.name
        resolved_kind = self._resolve_media_kind(kind, resolved_name)
        max_bytes = self.weixin_config.media_max_size_mb * 1024 * 1024
        size = await io.get_file_size(path)
        if size > max_bytes:
            raise WeixinServiceError(
                f"微信媒体超过大小限制: {size} > {max_bytes} bytes"
            )
        content = await io.read_bytes(path)
        account, runtime = await self._resolve_runtime(qq_id)
        receipt = await runtime.client.send_media(
            account.peer_id,
            content,
            kind=resolved_kind,
            file_name=resolved_name,
            caption=caption,
        )
        return receipt.client_id

    async def set_typing(self, qq_id: int, typing: bool) -> None:
        account, runtime = await self._resolve_runtime(qq_id)
        await runtime.client.set_typing(account.peer_id, typing)

    async def _complete_login(
        self,
        pending: _PendingLogin,
        result: QrPollResult,
        *,
        actor: str,
    ) -> WeixinAccount:
        credentials = result.credentials
        if credentials is None:
            raise WeixinServiceError("二维码登录未返回凭据")
        now = datetime.now().astimezone().isoformat(timespec="seconds")
        account = WeixinAccount(
            alias=pending.alias,
            qq_id=pending.qq_id,
            credentials=credentials,
            enabled=True,
            created_at=now,
            updated_at=now,
        )
        try:
            await self.store.save_account(account)
        except ValueError as exc:
            raise WeixinConflictError(str(exc)) from exc
        await self.store.append_audit(
            "account_bound",
            actor=actor,
            details={"alias": account.alias, "qq_id": account.qq_id},
        )
        async with self._lifecycle_lock:
            if self._running and self.weixin_config.enabled:
                await self._start_account_locked(account)
        return account

    async def _start_account_locked(self, account: WeixinAccount) -> None:
        if account.alias in self._runtimes:
            return
        stop_event = asyncio.Event()
        client = self._client_factory(
            account, self._state_store, self._client_options()
        )
        task = asyncio.create_task(
            self._run_account(account, client, stop_event),
            name=f"weixin:{account.alias}",
        )
        self._runtimes[account.alias] = _AccountRuntime(
            client=client,
            stop_event=stop_event,
            task=task,
        )

    async def _run_account(
        self,
        account: WeixinAccount,
        client: WeixinClientProtocol,
        stop_event: asyncio.Event,
    ) -> None:
        runtime: _AccountRuntime | None = None
        try:
            await client.start()
            runtime = self._runtimes.get(account.alias)
            if runtime is not None:
                runtime.connected = True
                runtime.last_error = ""
            await client.run(
                lambda message: self._handle_inbound(account.alias, client, message),
                stop_event=stop_event,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            safe_error = redact_string(str(exc))[:500]
            runtime = self._runtimes.get(account.alias)
            if runtime is not None:
                runtime.last_error = safe_error
            logger.exception("[微信] 帐号运行失败: alias=%s", account.alias)
        finally:
            runtime = self._runtimes.get(account.alias)
            if runtime is not None:
                runtime.connected = False
            try:
                await client.aclose()
            except Exception:
                logger.debug(
                    "[微信] 关闭帐号客户端失败: alias=%s", account.alias, exc_info=True
                )

    async def _stop_account_locked(self, alias: str) -> None:
        runtime = self._runtimes.pop(alias, None)
        if runtime is None:
            return
        runtime.stop_event.set()
        runtime.task.cancel()
        await asyncio.gather(runtime.task, return_exceptions=True)
        try:
            await runtime.client.aclose()
        except Exception:
            logger.debug("[微信] 关闭帐号客户端失败: alias=%s", alias, exc_info=True)

    async def _handle_inbound(
        self,
        alias: str,
        client: WeixinClientProtocol,
        message: InboundMessage,
    ) -> None:
        account = await self.store.get_account(alias)
        if account is None:
            return
        if (
            message.account_id != account.credentials.account_id
            or not message.from_user_id
            or message.from_user_id != account.peer_id
        ):
            await self.store.record_pending_peer(
                account_alias=alias,
                peer_id=message.from_user_id or "unknown",
                reason="unexpected_peer",
            )
            logger.warning("[微信] 已隔离未知来源: alias=%s", alias)
            return
        if not self.config.is_private_allowed(account.qq_id):
            logger.info(
                "[微信] 访问控制已忽略消息: alias=%s qq=%s", alias, account.qq_id
            )
            return
        if self.message_handler is None:
            logger.warning("[微信] 缺少消息处理器，已忽略已绑定消息: alias=%s", alias)
            return

        text_parts: list[str] = []
        message_content: list[dict[str, Any]] = []
        attachments: list[dict[str, str]] = []
        for index, item in enumerate(message.items):
            if item.type is MessageItemType.TEXT and item.text:
                text_parts.append(item.text)
                message_content.append({"type": "text", "data": {"text": item.text}})
            elif item.type is MessageItemType.VOICE and item.voice_transcript:
                text_parts.append(item.voice_transcript)
                message_content.append(
                    {"type": "text", "data": {"text": item.voice_transcript}}
                )
            if item.media_kind is None:
                continue
            try:
                downloaded = await client.download_media(item)
                ref = await self._register_inbound_media(
                    account=account,
                    message=message,
                    index=index,
                    media=downloaded,
                )
            except Exception:
                logger.warning(
                    "[微信] 下载入站附件失败: alias=%s message=%s index=%s",
                    alias,
                    message.message_id or message.client_id,
                    index,
                    exc_info=True,
                )
                continue
            if ref is not None:
                attachments.append(ref)
                message_content.append(
                    {
                        "type": ref.get("media_type", "file"),
                        "data": {"uid": ref["uid"]},
                    }
                )

        text = "\n".join(part for part in text_parts if part).strip()
        await self.message_handler.handle_weixin_private_message(
            qq_id=account.qq_id,
            text=text,
            message_content=message_content,
            attachments=attachments,
            sender_name=f"微信用户{account.qq_id}",
            message_id=(message.message_id or message.client_id or None),
            account_alias=account.alias,
        )

    async def _register_inbound_media(
        self,
        *,
        account: WeixinAccount,
        message: InboundMessage,
        index: int,
        media: DownloadedMedia,
    ) -> dict[str, str] | None:
        registry = self.attachment_registry
        if registry is None:
            return None
        kind = "record" if media.kind is MediaKind.VOICE else media.kind.value
        record = await registry.register_bytes(
            f"private:{account.qq_id}",
            media.content,
            kind=kind,
            display_name=media.file_name,
            source_kind="weixin_ilink",
            source_ref=(
                f"weixin:{account.alias}:{message.message_id or message.client_id}:{index}"
            ),
            mime_type=media.content_type,
        )
        return record.prompt_ref()

    async def _resolve_runtime(
        self, qq_id: int
    ) -> tuple[WeixinAccount, _AccountRuntime]:
        self._validate_qq_id(qq_id)
        account = await self.store.get_by_qq(qq_id)
        if account is None:
            raise WeixinNotFoundError(f"QQ {qq_id} 没有微信绑定")
        if not account.enabled:
            raise WeixinServiceError(f"微信帐号 {account.alias} 已禁用")
        runtime = self._runtimes.get(account.alias)
        if runtime is None or not runtime.connected:
            raise WeixinServiceError(f"微信帐号 {account.alias} 当前未连接")
        return account, runtime

    async def _require_privileged_confirmation(
        self,
        *,
        operation: str,
        alias: str,
        qq_id: int,
        confirmation_token: str | None,
        actor: str,
    ) -> None:
        if not self.config.is_admin(qq_id) and not self.config.is_superadmin(qq_id):
            return
        now = time.time()
        self._confirmations = {
            token: value
            for token, value in self._confirmations.items()
            if value.expires_at > now
        }
        token = str(confirmation_token or "").strip()
        confirmation = self._confirmations.get(token) if token else None
        if (
            confirmation is not None
            and confirmation.operation == operation
            and confirmation.alias == alias
            and confirmation.qq_id == qq_id
        ):
            self._confirmations.pop(token, None)
            await self.store.append_audit(
                "privileged_binding_confirmed",
                actor=actor,
                details={"operation": operation, "alias": alias, "qq_id": qq_id},
            )
            return
        new_token = secrets.token_urlsafe(24)
        expires_at = now + self.weixin_config.privileged_confirmation_ttl_seconds
        self._confirmations[new_token] = _Confirmation(
            operation=operation,
            alias=alias,
            qq_id=qq_id,
            expires_at=expires_at,
        )
        warning = (
            f"QQ {qq_id} 具有管理员权限。绑定后，微信私聊将继承该 QQ 的全部权限、"
            "历史、记忆与模型偏好。请确认微信帐号确由该身份本人控制。"
        )
        raise WeixinConfirmationRequired(new_token, warning, expires_at)

    def _get_login(self, session_id: str) -> _PendingLogin:
        normalized = str(session_id or "").strip()
        pending = self._logins.get(normalized)
        if pending is None:
            raise WeixinNotFoundError("二维码登录会话不存在或已过期")
        return pending

    def _ensure_available(self) -> None:
        if not self.weixin_config.enabled:
            raise WeixinServiceError("请先在 config.toml 中启用 [weixin].enabled")
        if self._closed:
            raise WeixinServiceError("微信服务已关闭")

    @staticmethod
    def _normalize_alias(alias: str) -> str:
        try:
            return normalize_alias(alias)
        except ValueError as exc:
            raise WeixinServiceError(str(exc)) from exc

    @staticmethod
    def _safe_upstream_error(exc: Exception) -> str:
        detail = redact_string(str(exc)).strip()[:500]
        return f"微信 iLink 请求失败: {detail or exc.__class__.__name__}"

    @staticmethod
    def _validate_qq_id(qq_id: int) -> None:
        if isinstance(qq_id, bool) or int(qq_id) <= 0:
            raise WeixinServiceError("QQ 号必须是正整数")

    @staticmethod
    def _resolve_media_kind(
        value: MediaKind | str | None,
        file_name: str,
    ) -> MediaKind:
        if isinstance(value, MediaKind):
            resolved = value
        elif value is not None:
            try:
                resolved = MediaKind(str(value).strip().lower())
            except ValueError as exc:
                raise WeixinServiceError(f"不支持的微信媒体类型: {value}") from exc
        else:
            mime_type = mimetypes.guess_type(file_name)[0] or ""
            if mime_type.startswith("image/"):
                resolved = MediaKind.IMAGE
            elif mime_type.startswith("video/"):
                resolved = MediaKind.VIDEO
            else:
                resolved = MediaKind.FILE
        if resolved is MediaKind.VOICE:
            raise WeixinServiceError("微信 iLink 暂不支持发送语音")
        return resolved
