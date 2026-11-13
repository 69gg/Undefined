"""WebUI 会话落盘：控制台重启后登录态保留，活跃会话滑动续期。"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from Undefined.config.webui_settings import WebUISettings
from Undefined.utils.io import write_json_sync as _real_write_json_sync
from Undefined.webui import core
from Undefined.webui.core import SessionStore
from Undefined.webui.routes import routes
from Undefined.webui.routes._shared import (
    SESSION_COOKIE,
    SESSION_STORE_APP_KEY,
    SETTINGS_APP_KEY,
    TOKEN_COOKIE,
)


def _make_app(path: Path) -> web.Application:
    app = web.Application()
    app[SESSION_STORE_APP_KEY] = SessionStore(storage_path=path, password="secret")
    app[SETTINGS_APP_KEY] = WebUISettings(
        url="127.0.0.1",
        port=8787,
        password="secret",
        autostart_bot=False,
        check_updates=False,
        using_default_password=False,
        config_exists=True,
    )
    app.add_routes(routes)
    return app


def test_default_ttls_are_long_lived() -> None:
    assert core.SESSION_TTL_SECONDS >= 30 * 24 * 60 * 60
    assert core.REFRESH_TOKEN_TTL_SECONDS >= 30 * 24 * 60 * 60


def test_sessions_survive_restart(tmp_path: Path) -> None:
    path = tmp_path / "sessions.json"
    store = SessionStore(storage_path=path)
    session_token = store.create()
    tokens = store.issue_auth_tokens()

    restarted = SessionStore(storage_path=path)

    assert restarted.is_valid(session_token, allowed_kinds={"session"})
    assert restarted.is_valid(str(tokens["access_token"]), allowed_kinds={"access"})
    assert restarted.is_valid(str(tokens["refresh_token"]), allowed_kinds={"refresh"})


def test_expired_sessions_are_dropped_on_load(tmp_path: Path) -> None:
    path = tmp_path / "sessions.json"
    now = time.time()
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "sessions": {
                    "alive": {"expires_at": now + 60, "kind": "session"},
                    "dead": {"expires_at": now - 1, "kind": "session"},
                    "bogus": {"expires_at": "not-a-number", "kind": "session"},
                },
            }
        ),
        encoding="utf-8",
    )

    store = SessionStore(storage_path=path)

    assert store.is_valid("alive", allowed_kinds={"session"})
    assert not store.is_valid("dead", allowed_kinds={"session"})
    assert not store.is_valid("bogus", allowed_kinds={"session"})


def test_revoke_and_clear_are_persisted(tmp_path: Path) -> None:
    path = tmp_path / "sessions.json"
    store = SessionStore(storage_path=path)
    token = store.create()
    store.revoke(token)
    assert not SessionStore(storage_path=path).is_valid(token)

    another = store.create()
    store.clear()
    assert not SessionStore(storage_path=path).is_valid(another)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["sessions"] == {}


def test_corrupt_file_does_not_break_startup(tmp_path: Path) -> None:
    path = tmp_path / "sessions.json"
    path.write_text("{not json", encoding="utf-8")

    store = SessionStore(storage_path=path)
    token = store.create()

    assert store.is_valid(token)
    assert SessionStore(storage_path=path).is_valid(token)


def test_invalid_utf8_file_does_not_break_startup(tmp_path: Path) -> None:
    path = tmp_path / "sessions.json"
    path.write_bytes(b"\xff\xfe\x00\x00")

    store = SessionStore(storage_path=path)
    token = store.create()

    assert store.is_valid(token)
    assert SessionStore(storage_path=path).is_valid(token)


def test_password_change_persists_invalidation(tmp_path: Path) -> None:
    path = tmp_path / "sessions.json"
    store = SessionStore(storage_path=path, password="old")
    token = store.create()

    # 用新密码启动会立即把空会话表和新指纹写回磁盘。
    SessionStore(storage_path=path, password="new")

    # 即使密码改回旧值，旧会话也不能复活。
    assert not SessionStore(storage_path=path, password="old").is_valid(token)


def _fail_write(*_args: object, **_kwargs: object) -> None:
    raise OSError("disk full")


def test_revoke_failure_restores_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "sessions.json"
    store = SessionStore(storage_path=path)
    token = store.create()
    monkeypatch.setattr("Undefined.webui.core.write_json_sync", _fail_write)

    with pytest.raises(OSError):
        store.revoke(token)

    assert store.is_valid(token)


def test_clear_failure_restores_sessions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "sessions.json"
    store = SessionStore(storage_path=path)
    token = store.create()
    monkeypatch.setattr("Undefined.webui.core.write_json_sync", _fail_write)

    with pytest.raises(OSError):
        store.clear()

    assert store.is_valid(token)


def test_refresh_failure_restores_old_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "sessions.json"
    store = SessionStore(storage_path=path)
    tokens = store.issue_auth_tokens()
    refresh_token = str(tokens["refresh_token"])
    monkeypatch.setattr("Undefined.webui.core.write_json_sync", _fail_write)

    with pytest.raises(OSError):
        store.refresh_auth_tokens(refresh_token)

    assert store.is_valid(refresh_token, allowed_kinds={"refresh"})


def test_set_password_failure_restores_sessions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "sessions.json"
    store = SessionStore(storage_path=path, password="old")
    token = store.create()
    monkeypatch.setattr("Undefined.webui.core.write_json_sync", _fail_write)

    with pytest.raises(OSError):
        store.set_password("new")

    assert store.is_valid(token)


def test_password_change_invalidates_persisted_sessions(tmp_path: Path) -> None:
    path = tmp_path / "sessions.json"
    store = SessionStore(storage_path=path, password="old")
    token = store.create()

    assert SessionStore(storage_path=path, password="old").is_valid(token)
    assert not SessionStore(storage_path=path, password="new").is_valid(token)


def test_set_password_clears_sessions_and_updates_fingerprint(tmp_path: Path) -> None:
    path = tmp_path / "sessions.json"
    store = SessionStore(storage_path=path, password="old")
    token = store.create()

    store.set_password("new")

    assert not store.is_valid(token)
    assert not SessionStore(storage_path=path, password="old").is_valid(token)
    assert not SessionStore(storage_path=path, password="new").is_valid(token)


def test_active_session_slides_expiry(tmp_path: Path) -> None:
    path = tmp_path / "sessions.json"
    store = SessionStore(ttl_seconds=100, storage_path=path)
    token = store.create()
    # 模拟会话已消耗超过一半有效期。
    store._sessions[token].expires_at = time.time() + 10
    shortened = store._sessions[token].expires_at

    assert store.is_valid(token, allowed_kinds={"session"})
    assert store._sessions[token].expires_at > shortened + 50

    restarted = SessionStore(ttl_seconds=100, storage_path=path)
    assert restarted._sessions[token].expires_at > shortened + 50


def test_refresh_rotation_is_persisted(tmp_path: Path) -> None:
    path = tmp_path / "sessions.json"
    store = SessionStore(storage_path=path)
    first = store.issue_auth_tokens()

    rotated = store.refresh_auth_tokens(str(first["refresh_token"]))

    assert rotated is not None
    assert not store.is_valid(str(first["refresh_token"]), allowed_kinds={"refresh"})
    restarted = SessionStore(storage_path=path)
    assert restarted.is_valid(str(rotated["refresh_token"]), allowed_kinds={"refresh"})
    assert restarted.is_valid(str(rotated["access_token"]), allowed_kinds={"access"})


def test_expired_refresh_token_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "sessions.json"
    store = SessionStore(storage_path=path)
    tokens = store.issue_auth_tokens()
    refresh_token = str(tokens["refresh_token"])
    store._sessions[refresh_token].expires_at = time.time() - 1

    assert store.refresh_auth_tokens(refresh_token) is None


@pytest.mark.skipif(os.name == "nt", reason="POSIX 权限位")
def test_persisted_file_is_owner_only(tmp_path: Path) -> None:
    path = tmp_path / "sessions.json"
    SessionStore(storage_path=path).create()

    assert (path.stat().st_mode & 0o777) == 0o600


async def test_cookie_login_survives_restart(tmp_path: Path) -> None:
    path = tmp_path / "sessions.json"

    async with TestClient(TestServer(_make_app(path))) as client:
        response = await client.post(
            "/api/v1/management/auth/login", json={"password": "secret"}
        )
        assert response.status == 200
        assert response.cookies[SESSION_COOKIE]["max-age"] == str(
            core.SESSION_TTL_SECONDS
        )
        assert response.cookies[TOKEN_COOKIE]["max-age"] == str(
            core.REFRESH_TOKEN_TTL_SECONDS
        )
        cookies = {
            SESSION_COOKIE: response.cookies[SESSION_COOKIE].value,
            TOKEN_COOKIE: response.cookies[TOKEN_COOKIE].value,
        }

    # 模拟控制台进程重启：同一会话文件重新加载。
    async with TestClient(TestServer(_make_app(path))) as restarted:
        response = await restarted.get(
            "/api/v1/management/auth/session", cookies=cookies
        )
        assert response.status == 200
        payload = await response.json()
        assert payload["authenticated"] is True


async def test_refresh_persistence_failure_returns_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "sessions.json"
    app = _make_app(path)
    real_write = _real_write_json_sync
    async with TestClient(TestServer(app)) as client:
        login = await client.post(
            "/api/v1/management/auth/login", json={"password": "secret"}
        )
        refresh_token = (await login.json())["refresh_token"]
        monkeypatch.setattr("Undefined.webui.core.write_json_sync", _fail_write)

        response = await client.post(
            "/api/v1/management/auth/refresh",
            json={"refresh_token": refresh_token},
        )

        assert response.status == 500
        assert (await response.json())["success"] is False
        monkeypatch.setattr("Undefined.webui.core.write_json_sync", real_write)
        assert app[SESSION_STORE_APP_KEY].is_valid(
            refresh_token, allowed_kinds={"refresh"}
        )


async def test_logout_persistence_failure_keeps_cookies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "sessions.json"
    app = _make_app(path)
    async with TestClient(TestServer(app)) as client:
        login = await client.post(
            "/api/v1/management/auth/login", json={"password": "secret"}
        )
        cookies = {
            SESSION_COOKIE: login.cookies[SESSION_COOKIE].value,
            TOKEN_COOKIE: login.cookies[TOKEN_COOKIE].value,
        }
        monkeypatch.setattr("Undefined.webui.core.write_json_sync", _fail_write)

        response = await client.post("/api/v1/management/auth/logout", cookies=cookies)

        assert response.status == 500
        assert (await response.json())["success"] is False
        assert response.headers.getall("Set-Cookie", []) == []
