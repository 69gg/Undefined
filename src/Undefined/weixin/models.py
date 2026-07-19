"""微信接入的本地领域模型。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from weixin_ilink_client import WeixinCredentials


@dataclass(frozen=True, slots=True)
class WeixinAccount:
    """一个微信 ClawBot 帐号到逻辑 QQ 身份的绑定。"""

    alias: str
    qq_id: int
    credentials: WeixinCredentials
    enabled: bool
    created_at: str
    updated_at: str

    @property
    def peer_id(self) -> str:
        return self.credentials.user_id

    def to_storage_dict(self) -> dict[str, Any]:
        return {
            "alias": self.alias,
            "qq_id": self.qq_id,
            "account_id": self.credentials.account_id,
            "bot_token": self.credentials.bot_token,
            "base_url": self.credentials.base_url,
            "user_id": self.credentials.user_id,
            "enabled": self.enabled,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    def to_public_dict(
        self, *, connected: bool = False, error: str = ""
    ) -> dict[str, Any]:
        return {
            "alias": self.alias,
            "qq_id": self.qq_id,
            "address": f"wechat:{self.qq_id}",
            "enabled": self.enabled,
            "connected": connected,
            "error": error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_storage_dict(cls, value: object) -> WeixinAccount | None:
        if not isinstance(value, dict):
            return None
        alias = _string(value.get("alias"))
        account_id = _string(value.get("account_id"))
        bot_token = _string(value.get("bot_token"))
        base_url = _string(value.get("base_url"))
        user_id = _string(value.get("user_id"))
        qq_id = _positive_int(value.get("qq_id"))
        if not all((alias, account_id, bot_token, base_url, user_id)) or qq_id is None:
            return None
        return cls(
            alias=alias,
            qq_id=qq_id,
            credentials=WeixinCredentials(account_id, bot_token, base_url, user_id),
            enabled=bool(value.get("enabled", True)),
            created_at=_string(value.get("created_at")),
            updated_at=_string(value.get("updated_at")),
        )


@dataclass(frozen=True, slots=True)
class WeixinPendingPeer:
    id: str
    account_alias: str
    peer_id: str
    reason: str
    first_seen_at: str
    last_seen_at: str
    count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "account_alias": self.account_alias,
            "peer_id": self.peer_id,
            "reason": self.reason,
            "first_seen_at": self.first_seen_at,
            "last_seen_at": self.last_seen_at,
            "count": self.count,
        }

    @classmethod
    def from_dict(cls, value: object) -> WeixinPendingPeer | None:
        if not isinstance(value, dict):
            return None
        record_id = _string(value.get("id"))
        alias = _string(value.get("account_alias"))
        peer_id = _string(value.get("peer_id"))
        if not record_id or not alias or not peer_id:
            return None
        return cls(
            id=record_id,
            account_alias=alias,
            peer_id=peer_id,
            reason=_string(value.get("reason")) or "unexpected_peer",
            first_seen_at=_string(value.get("first_seen_at")),
            last_seen_at=_string(value.get("last_seen_at")),
            count=max(1, _positive_int(value.get("count")) or 1),
        )


@dataclass(frozen=True, slots=True)
class WeixinAuditEntry:
    id: str
    action: str
    actor: str
    timestamp: str
    details: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "action": self.action,
            "actor": self.actor,
            "timestamp": self.timestamp,
            "details": dict(self.details),
        }

    @classmethod
    def from_dict(cls, value: object) -> WeixinAuditEntry | None:
        if not isinstance(value, dict):
            return None
        record_id = _string(value.get("id"))
        action = _string(value.get("action"))
        if not record_id or not action:
            return None
        details_raw = value.get("details")
        return cls(
            id=record_id,
            action=action,
            actor=_string(value.get("actor")) or "system",
            timestamp=_string(value.get("timestamp")),
            details=dict(details_raw) if isinstance(details_raw, dict) else {},
        )


def normalize_alias(value: str) -> str:
    alias = str(value or "").strip()
    if not alias:
        raise ValueError("帐号别名不能为空")
    if len(alias) > 64:
        raise ValueError("帐号别名不能超过 64 个字符")
    if any(character in alias for character in ("/", "\\", "\x00")):
        raise ValueError("帐号别名包含非法字符")
    return alias


def _string(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _positive_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if not isinstance(value, (int, float, str)):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None
