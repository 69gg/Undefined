from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from weixin_ilink_client import WeixinCredentials

from Undefined.config import WeixinConfig
from Undefined.weixin.models import WeixinAccount
from Undefined.weixin.store import UndefinedIlinkStateStore, WeixinStore


def _account(alias: str, qq_id: int, account_id: str = "bot-1") -> WeixinAccount:
    return WeixinAccount(
        alias=alias,
        qq_id=qq_id,
        credentials=WeixinCredentials(
            account_id=account_id,
            bot_token=f"token-{account_id}",
            base_url="https://ilink.example.test",
            user_id=f"peer-{account_id}",
        ),
        enabled=True,
        created_at="2026-01-01T00:00:00+08:00",
        updated_at="2026-01-01T00:00:00+08:00",
    )


@pytest.mark.asyncio
async def test_weixin_store_enforces_one_binding_per_qq(tmp_path: Path) -> None:
    store = WeixinStore(WeixinConfig(state_dir=str(tmp_path)))
    await store.save_account(_account("primary", 10001))

    with pytest.raises(ValueError, match="已绑定"):
        await store.save_account(_account("other", 10001, "bot-2"))

    assert (await store.get_by_qq(10001)) == _account("primary", 10001)
    payload = json.loads((tmp_path / "bindings.json").read_text(encoding="utf-8"))
    assert payload["accounts"]["primary"]["bot_token"] == "token-bot-1"
    if os.name == "posix":
        assert (tmp_path / "bindings.json").stat().st_mode & 0o777 == 0o600


@pytest.mark.asyncio
async def test_pending_peer_never_persists_message_content(tmp_path: Path) -> None:
    store = WeixinStore(WeixinConfig(state_dir=str(tmp_path)))
    first = await store.record_pending_peer(
        account_alias="primary",
        peer_id="unexpected-peer",
    )
    second = await store.record_pending_peer(
        account_alias="primary",
        peer_id="unexpected-peer",
    )

    assert first.id == second.id
    assert second.count == 2
    raw = (tmp_path / "bindings.json").read_text(encoding="utf-8")
    assert "unexpected-peer" in raw
    assert "message" not in raw


@pytest.mark.asyncio
async def test_ilink_state_store_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "runtime.json"
    store = UndefinedIlinkStateStore(path, seen_limit=2)
    await store.set_cursor("account", "cursor-1")
    await store.set_context_token("account", "peer", "context-token")
    await store.mark_seen("account", "m1")
    await store.mark_seen("account", "m2")
    await store.mark_seen("account", "m3")
    await store.set_pause_until("account", 123.5)

    reloaded = UndefinedIlinkStateStore(path, seen_limit=2)
    assert await reloaded.get_cursor("account") == "cursor-1"
    assert await reloaded.get_context_token("account", "peer") == "context-token"
    assert await reloaded.has_seen("account", "m1") is False
    assert await reloaded.has_seen("account", "m3") is True
    assert await reloaded.get_pause_until("account") == 123.5


@pytest.mark.asyncio
async def test_ilink_state_store_skips_unchanged_writes(tmp_path: Path) -> None:
    path = tmp_path / "runtime.json"
    store = UndefinedIlinkStateStore(path)
    await store.set_cursor("account", "cursor-1")
    await store.set_context_token("account", "peer", "context-token")
    await store.set_pause_until("account", 123.5)
    mtime = path.stat().st_mtime_ns

    await store.set_cursor("account", "cursor-1")
    await store.set_context_token("account", "peer", "context-token")
    await store.set_pause_until("account", 123.5)
    assert path.stat().st_mtime_ns == mtime

    await store.set_cursor("account", "cursor-2")
    await store.set_context_token("account", "peer", "context-token-2")
    await store.set_pause_until("account", 456.5)
    reloaded = UndefinedIlinkStateStore(path)
    assert await reloaded.get_cursor("account") == "cursor-2"
    assert await reloaded.get_context_token("account", "peer") == "context-token-2"
    assert await reloaded.get_pause_until("account") == 456.5


@pytest.mark.asyncio
async def test_ilink_state_store_delete_account_removes_all_runtime_state(
    tmp_path: Path,
) -> None:
    path = tmp_path / "runtime.json"
    store = UndefinedIlinkStateStore(path)
    await store.set_cursor("account", "cursor-1")
    await store.set_context_token("account", "peer", "context-token")
    await store.mark_seen("account", "m1")
    await store.set_pause_until("account", 123.5)

    await store.delete_account("account")

    reloaded = UndefinedIlinkStateStore(path)
    assert await reloaded.get_cursor("account") == ""
    assert await reloaded.get_context_token("account", "peer") == ""
    assert await reloaded.has_seen("account", "m1") is False
    assert await reloaded.get_pause_until("account") == 0.0
