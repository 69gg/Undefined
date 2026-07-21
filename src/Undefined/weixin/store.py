"""微信绑定、隔离记录、审计和 SDK 运行状态的持久化。"""

from __future__ import annotations

import asyncio
import hashlib
import os
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from Undefined.config.models import WeixinConfig
from Undefined.utils import io
from Undefined.weixin.models import (
    WeixinAccount,
    WeixinAuditEntry,
    WeixinPendingPeer,
    normalize_alias,
)


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


async def _secure_file(path: Path) -> None:
    if os.name == "posix" and await io.exists(path):
        await io.chmod(path, 0o600)


class WeixinStore:
    """单进程使用的微信绑定存储。"""

    def __init__(self, config: WeixinConfig) -> None:
        self._config = config
        self._path = Path(config.state_dir).expanduser() / "bindings.json"
        self._lock = asyncio.Lock()
        self._loaded = False
        self._accounts: dict[str, WeixinAccount] = {}
        self._pending: dict[str, WeixinPendingPeer] = {}
        self._audit: list[WeixinAuditEntry] = []

    async def list_accounts(self) -> list[WeixinAccount]:
        async with self._lock:
            await self._load_locked()
            return sorted(self._accounts.values(), key=lambda item: item.alias)

    async def get_account(self, alias: str) -> WeixinAccount | None:
        normalized = normalize_alias(alias)
        async with self._lock:
            await self._load_locked()
            return self._accounts.get(normalized)

    async def get_by_qq(self, qq_id: int) -> WeixinAccount | None:
        async with self._lock:
            await self._load_locked()
            return next(
                (
                    account
                    for account in self._accounts.values()
                    if account.qq_id == qq_id
                ),
                None,
            )

    async def get_by_account_id(self, account_id: str) -> WeixinAccount | None:
        async with self._lock:
            await self._load_locked()
            return next(
                (
                    account
                    for account in self._accounts.values()
                    if account.credentials.account_id == account_id
                ),
                None,
            )

    async def local_tokens(self, *, limit: int = 10) -> tuple[str, ...]:
        accounts = await self.list_accounts()
        tokens = [item.credentials.bot_token for item in accounts]
        return tuple(tokens[-max(0, limit) :])

    async def save_account(self, account: WeixinAccount) -> None:
        normalized = normalize_alias(account.alias)
        if account.qq_id <= 0:
            raise ValueError("QQ 号必须是正整数")
        async with self._lock:
            await self._load_locked()
            for alias, existing in self._accounts.items():
                if alias != normalized and existing.qq_id == account.qq_id:
                    raise ValueError(f"QQ {account.qq_id} 已绑定帐号 {alias}")
                if (
                    alias != normalized
                    and existing.credentials.account_id
                    == account.credentials.account_id
                ):
                    raise ValueError(f"该微信 ClawBot 已绑定帐号 {alias}")
            self._accounts[normalized] = account
            await self._write_locked()

    async def remove_account(self, alias: str) -> WeixinAccount | None:
        normalized = normalize_alias(alias)
        async with self._lock:
            await self._load_locked()
            removed = self._accounts.pop(normalized, None)
            if removed is not None:
                await self._write_locked()
            return removed

    async def set_account_enabled(self, alias: str, enabled: bool) -> WeixinAccount:
        normalized = normalize_alias(alias)
        async with self._lock:
            await self._load_locked()
            existing = self._accounts.get(normalized)
            if existing is None:
                raise KeyError(normalized)
            updated = WeixinAccount(
                alias=existing.alias,
                qq_id=existing.qq_id,
                credentials=existing.credentials,
                enabled=bool(enabled),
                created_at=existing.created_at,
                updated_at=_now_iso(),
            )
            self._accounts[normalized] = updated
            await self._write_locked()
            return updated

    async def rebind_account(self, alias: str, qq_id: int) -> WeixinAccount:
        normalized = normalize_alias(alias)
        if qq_id <= 0:
            raise ValueError("QQ 号必须是正整数")
        async with self._lock:
            await self._load_locked()
            existing = self._accounts.get(normalized)
            if existing is None:
                raise KeyError(normalized)
            conflict = next(
                (
                    account
                    for key, account in self._accounts.items()
                    if key != normalized and account.qq_id == qq_id
                ),
                None,
            )
            if conflict is not None:
                raise ValueError(f"QQ {qq_id} 已绑定帐号 {conflict.alias}")
            updated = WeixinAccount(
                alias=existing.alias,
                qq_id=qq_id,
                credentials=existing.credentials,
                enabled=existing.enabled,
                created_at=existing.created_at,
                updated_at=_now_iso(),
            )
            self._accounts[normalized] = updated
            await self._write_locked()
            return updated

    async def record_pending_peer(
        self,
        *,
        account_alias: str,
        peer_id: str,
        reason: str = "unexpected_peer",
    ) -> WeixinPendingPeer:
        normalized_alias = normalize_alias(account_alias)
        normalized_peer = str(peer_id or "").strip()
        if not normalized_peer:
            raise ValueError("peer_id 不能为空")
        digest = hashlib.sha256(
            f"{normalized_alias}\0{normalized_peer}".encode("utf-8")
        ).hexdigest()[:16]
        now = _now_iso()
        async with self._lock:
            await self._load_locked()
            existing = self._pending.get(digest)
            record = WeixinPendingPeer(
                id=digest,
                account_alias=normalized_alias,
                peer_id=normalized_peer,
                reason=str(reason or "unexpected_peer"),
                first_seen_at=existing.first_seen_at if existing else now,
                last_seen_at=now,
                count=(existing.count + 1) if existing else 1,
            )
            self._pending[digest] = record
            if len(self._pending) > self._config.pending_max_records:
                oldest = sorted(
                    self._pending.values(), key=lambda item: item.last_seen_at
                )[: len(self._pending) - self._config.pending_max_records]
                for item in oldest:
                    self._pending.pop(item.id, None)
            await self._write_locked()
            return record

    async def list_pending_peers(self) -> list[WeixinPendingPeer]:
        async with self._lock:
            await self._load_locked()
            return sorted(
                self._pending.values(), key=lambda item: item.last_seen_at, reverse=True
            )

    async def dismiss_pending_peer(self, record_id: str) -> bool:
        async with self._lock:
            await self._load_locked()
            removed = self._pending.pop(str(record_id).strip(), None)
            if removed is not None:
                await self._write_locked()
            return removed is not None

    async def append_audit(
        self,
        action: str,
        *,
        actor: str,
        details: dict[str, Any] | None = None,
    ) -> WeixinAuditEntry:
        entry = WeixinAuditEntry(
            id=uuid4().hex,
            action=str(action).strip(),
            actor=str(actor or "system").strip(),
            timestamp=_now_iso(),
            details=dict(details or {}),
        )
        async with self._lock:
            await self._load_locked()
            self._audit.append(entry)
            if len(self._audit) > self._config.audit_max_records:
                self._audit = self._audit[-self._config.audit_max_records :]
            await self._write_locked()
        return entry

    async def list_audit(self, *, limit: int = 100) -> list[WeixinAuditEntry]:
        async with self._lock:
            await self._load_locked()
            resolved_limit = max(1, min(int(limit), self._config.audit_max_records))
            return list(reversed(self._audit[-resolved_limit:]))

    async def _load_locked(self) -> None:
        if self._loaded:
            return
        raw = await io.read_json(self._path, use_lock=True)
        payload = raw if isinstance(raw, dict) else {}
        accounts_raw = payload.get("accounts")
        if isinstance(accounts_raw, dict):
            for alias, value in accounts_raw.items():
                account = WeixinAccount.from_storage_dict(value)
                if account is not None and account.alias == alias:
                    self._accounts[alias] = account
        pending_raw = payload.get("pending")
        if isinstance(pending_raw, list):
            for value in pending_raw:
                record = WeixinPendingPeer.from_dict(value)
                if record is not None:
                    self._pending[record.id] = record
        audit_raw = payload.get("audit")
        if isinstance(audit_raw, list):
            self._audit = [
                entry
                for value in audit_raw
                if (entry := WeixinAuditEntry.from_dict(value)) is not None
            ][-self._config.audit_max_records :]
        self._loaded = True

    async def _write_locked(self) -> None:
        payload = {
            "version": 1,
            "accounts": {
                alias: account.to_storage_dict()
                for alias, account in self._accounts.items()
            },
            "pending": [item.to_dict() for item in self._pending.values()],
            "audit": [item.to_dict() for item in self._audit],
        }
        await io.write_json(self._path, payload, use_lock=True)
        await _secure_file(self._path)


class UndefinedIlinkStateStore:
    """使用 Undefined 原子 IO 的 iLink ``StateStore`` 实现。"""

    def __init__(self, path: Path, *, seen_limit: int = 2000) -> None:
        self._path = path
        self._seen_limit = max(1, int(seen_limit))
        self._lock = asyncio.Lock()
        self._loaded = False
        self._data: dict[str, Any] = self._empty_data()

    async def get_cursor(self, account_id: str) -> str:
        async with self._lock:
            await self._load_locked()
            return self._string_mapping("cursors").get(account_id, "")

    async def set_cursor(self, account_id: str, cursor: str) -> None:
        async with self._lock:
            await self._load_locked()
            cursors = self._string_mapping("cursors")
            if cursors.get(account_id, "") == cursor:
                return
            cursors[account_id] = cursor
            await self._write_locked()

    async def get_context_token(self, account_id: str, peer_id: str) -> str:
        async with self._lock:
            await self._load_locked()
            return (
                self._nested_string_mapping("context_tokens")
                .get(account_id, {})
                .get(peer_id, "")
            )

    async def set_context_token(
        self, account_id: str, peer_id: str, token: str
    ) -> None:
        async with self._lock:
            await self._load_locked()
            context_tokens = self._nested_string_mapping("context_tokens")
            if context_tokens.get(account_id, {}).get(peer_id, "") == token:
                return
            context_tokens.setdefault(account_id, {})[peer_id] = token
            await self._write_locked()

    async def has_seen(self, account_id: str, message_key: str) -> bool:
        async with self._lock:
            await self._load_locked()
            return message_key in self._list_mapping("seen").get(account_id, [])

    async def mark_seen(self, account_id: str, message_key: str) -> None:
        async with self._lock:
            await self._load_locked()
            values = self._list_mapping("seen").setdefault(account_id, [])
            if message_key in values:
                return
            values.append(message_key)
            if len(values) > self._seen_limit:
                del values[: len(values) - self._seen_limit]
            await self._write_locked()

    async def get_pause_until(self, account_id: str) -> float:
        async with self._lock:
            await self._load_locked()
            return self._number_mapping("pause_until").get(account_id, 0.0)

    async def set_pause_until(self, account_id: str, timestamp: float) -> None:
        async with self._lock:
            await self._load_locked()
            pause_until = self._number_mapping("pause_until")
            if pause_until.get(account_id, 0.0) == float(timestamp):
                return
            pause_until[account_id] = float(timestamp)
            await self._write_locked()

    async def delete_account(self, account_id: str) -> None:
        """删除一个帐号的游标、上下文 token、去重和退避状态。"""
        normalized = str(account_id or "").strip()
        if not normalized:
            return
        async with self._lock:
            await self._load_locked()
            self._string_mapping("cursors").pop(normalized, None)
            self._nested_string_mapping("context_tokens").pop(normalized, None)
            self._list_mapping("seen").pop(normalized, None)
            self._number_mapping("pause_until").pop(normalized, None)
            await self._write_locked()

    @staticmethod
    def _empty_data() -> dict[str, Any]:
        return {
            "version": 1,
            "cursors": {},
            "context_tokens": {},
            "seen": {},
            "pause_until": {},
        }

    async def _load_locked(self) -> None:
        if self._loaded:
            return
        raw = await io.read_json(self._path, use_lock=True)
        if isinstance(raw, dict):
            for key in ("cursors", "context_tokens", "seen", "pause_until"):
                value = raw.get(key)
                if isinstance(value, dict):
                    self._data[key] = value
        self._loaded = True

    async def _write_locked(self) -> None:
        await io.write_json(self._path, self._data, use_lock=True)
        await _secure_file(self._path)

    def _string_mapping(self, key: str) -> dict[str, str]:
        value = self._data[key]
        if not isinstance(value, dict):
            value = {}
            self._data[key] = value
        return value

    def _nested_string_mapping(self, key: str) -> dict[str, dict[str, str]]:
        value = self._data[key]
        if not isinstance(value, dict):
            value = {}
            self._data[key] = value
        return value

    def _list_mapping(self, key: str) -> dict[str, list[str]]:
        value = self._data[key]
        if not isinstance(value, dict):
            value = {}
            self._data[key] = value
        return value

    def _number_mapping(self, key: str) -> dict[str, float]:
        value = self._data[key]
        if not isinstance(value, dict):
            value = {}
            self._data[key] = value
        return value
