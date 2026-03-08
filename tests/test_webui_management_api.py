from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any, cast

from aiohttp import web

from Undefined.webui.app import create_app
from Undefined.webui.core import SessionStore
from Undefined.webui.routes import _auth, _system
from Undefined.webui.routes._shared import (
    SESSION_COOKIE,
    SESSION_STORE_APP_KEY,
    SETTINGS_APP_KEY,
)


class DummyRequest(SimpleNamespace):
    async def json(self) -> dict[str, object]:
        return dict(getattr(self, "_json", {}))


def _request(
    *,
    json_body: dict[str, object] | None = None,
    headers: dict[str, str] | None = None,
    cookies: dict[str, str] | None = None,
    settings: object | None = None,
    session_store: SessionStore | None = None,
) -> DummyRequest:
    return DummyRequest(
        _json=json_body or {},
        headers=headers or {},
        cookies=cookies or {},
        app={
            SETTINGS_APP_KEY: settings
            or SimpleNamespace(
                url="127.0.0.1",
                port=8787,
                password="secret",
                using_default_password=False,
                config_exists=True,
            ),
            SESSION_STORE_APP_KEY: session_store or SessionStore(),
        },
        remote="127.0.0.1",
        transport=None,
    )


def _json_payload(response: web.StreamResponse) -> dict[str, object]:
    payload_text = cast(web.Response, response).text
    assert payload_text is not None
    return cast(dict[str, object], json.loads(payload_text))


def test_session_store_issues_and_refreshes_auth_tokens() -> None:
    session_store = SessionStore()

    first = session_store.issue_auth_tokens()
    access_token = cast(str, first["access_token"])
    refresh_token = cast(str, first["refresh_token"])
    assert session_store.is_valid(access_token, allowed_kinds={"access"})
    assert session_store.is_valid(refresh_token, allowed_kinds={"refresh"})

    second = session_store.refresh_auth_tokens(refresh_token)
    assert second is not None
    assert second["access_token"] != first["access_token"]
    assert second["refresh_token"] != first["refresh_token"]
    assert not session_store.is_valid(refresh_token, allowed_kinds={"refresh"})


async def test_login_handler_returns_cookie_and_bearer_tokens() -> None:
    session_store = SessionStore()
    request = _request(json_body={"password": "secret"}, session_store=session_store)

    response = await _auth.login_handler(cast(web.Request, cast(Any, request)))
    payload = _json_payload(response)
    access_token = payload["access_token"]
    refresh_token = payload["refresh_token"]

    assert payload["success"] is True
    assert isinstance(access_token, str)
    assert isinstance(refresh_token, str)
    assert response.cookies[SESSION_COOKIE].value
    assert session_store.is_valid(access_token, allowed_kinds={"access"})
    assert session_store.is_valid(refresh_token, allowed_kinds={"refresh"})


async def test_refresh_handler_rotates_access_token() -> None:
    session_store = SessionStore()
    tokens = session_store.issue_auth_tokens()
    request = _request(
        json_body={"refresh_token": tokens["refresh_token"]},
        session_store=session_store,
    )

    response = await _auth.refresh_handler(cast(web.Request, cast(Any, request)))
    payload = _json_payload(response)

    assert payload["success"] is True
    assert payload["access_token"] != tokens["access_token"]
    assert payload["refresh_token"] != tokens["refresh_token"]
    assert session_store.is_valid(
        cast(str, payload["access_token"]), allowed_kinds={"access"}
    )


async def test_bootstrap_probe_handler_reports_management_state(
    monkeypatch: Any,
) -> None:
    session_store = SessionStore()
    tokens = session_store.issue_auth_tokens()
    request = _request(
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
        session_store=session_store,
    )
    monkeypatch.setattr(
        _system,
        "load_bootstrap_probe_data",
        lambda: {
            "config_exists": True,
            "config_source": "config.toml",
            "toml_valid": True,
            "toml_message": "OK",
            "config_valid": False,
            "validation_error": "missing onebot.ws_url",
            "using_default_password": False,
            "danger_defaults": [],
        },
    )

    async def _fake_runtime() -> tuple[bool, bool, str]:
        return True, False, "connection refused"

    monkeypatch.setattr(_system, "_runtime_health_status", _fake_runtime)

    response = await _system.bootstrap_probe_handler(
        cast(web.Request, cast(Any, request))
    )
    payload = _json_payload(response)

    assert payload["config_exists"] is True
    assert payload["runtime_enabled"] is True
    assert payload["runtime_reachable"] is False
    assert payload["auth_mode"] == "token"
    assert payload["advice"]


def test_create_app_registers_management_routes() -> None:
    app = create_app()
    routes = {
        (route.method, cast(Any, route.resource).canonical)
        for route in app.router.routes()
        if getattr(route, "resource", None) is not None
        and hasattr(route.resource, "canonical")
    }
    assert ("POST", "/api/v1/management/auth/login") in routes
    assert ("POST", "/api/v1/management/auth/refresh") in routes
    assert ("GET", "/api/v1/management/probes/bootstrap") in routes
    assert ("GET", "/api/v1/management/runtime/meta") in routes
    assert ("POST", "/api/v1/management/config/validate") in routes
    assert ("POST", "/api/v1/management/bot/start") in routes
