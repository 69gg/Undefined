from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any, cast

from aiohttp import web

from Undefined.api import _helpers as runtime_api_helpers
from Undefined.webui import app as webui_app
from Undefined.webui.app import create_app
from Undefined.webui.core import SessionStore
from Undefined.webui.routes import _auth, _config, _index, _memes, _shared, _system
from Undefined.webui.routes._shared import (
    REDIRECT_TO_CONFIG_ONCE_APP_KEY,
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
    query: dict[str, str] | None = None,
    settings: object | None = None,
    session_store: SessionStore | None = None,
) -> DummyRequest:
    return DummyRequest(
        _json=json_body or {},
        headers=headers or {},
        cookies=cookies or {},
        query=query or {},
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
            REDIRECT_TO_CONFIG_ONCE_APP_KEY: False,
        },
        remote="127.0.0.1",
        scheme="http",
        host="127.0.0.1:8787",
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


async def test_sync_config_template_handler_preview_skips_reload(
    monkeypatch: Any,
) -> None:
    request = _request(query={"write": "false"})
    calls: list[tuple[str, object, object]] = []

    async def _fake_to_thread(func: Any, *args: Any, **kwargs: Any) -> Any:
        return func(*args, **kwargs)

    def _fake_validate_required_config() -> tuple[bool, str]:
        calls.append(("validate", None, None))
        return True, "OK"

    def _fake_sync_config_file(*, write: bool = True, prune: bool = False) -> Any:
        calls.append(("sync", write, prune))
        return SimpleNamespace(
            added_paths=["models.chat.api_mode"],
            removed_paths=["models.chat.extra"],
        )

    monkeypatch.setattr(_config, "check_auth", lambda _request: True)
    monkeypatch.setattr(
        cast(Any, getattr(_config, "asyncio")), "to_thread", _fake_to_thread
    )
    monkeypatch.setattr(_config, "sync_config_file", _fake_sync_config_file)
    monkeypatch.setattr(
        _config,
        "get_config_manager",
        lambda: SimpleNamespace(
            reload=lambda: calls.append(("reload", None, None)),
        ),
    )
    monkeypatch.setattr(
        _config, "validate_required_config", _fake_validate_required_config
    )

    response = await _config.sync_config_template_handler(
        cast(web.Request, cast(Any, request))
    )
    payload = _json_payload(response)

    assert payload["success"] is True
    assert payload["preview"] is True
    assert payload["warning"] is None
    assert payload["added_count"] == 1
    assert payload["removed_count"] == 1
    assert calls == [("sync", False, False)]


async def test_sync_config_template_handler_write_reloads_and_validates(
    monkeypatch: Any,
) -> None:
    request = _request(query={"prune": "true"})
    calls: list[tuple[str, object, object]] = []

    async def _fake_to_thread(func: Any, *args: Any, **kwargs: Any) -> Any:
        return func(*args, **kwargs)

    def _fake_validate_required_config() -> tuple[bool, str]:
        calls.append(("validate", None, None))
        return False, "missing required field"

    def _fake_sync_config_file(*, write: bool = True, prune: bool = False) -> Any:
        calls.append(("sync", write, prune))
        return SimpleNamespace(
            added_paths=[],
            removed_paths=["models.chat.extra"],
        )

    monkeypatch.setattr(_config, "check_auth", lambda _request: True)
    monkeypatch.setattr(
        cast(Any, getattr(_config, "asyncio")), "to_thread", _fake_to_thread
    )
    monkeypatch.setattr(_config, "sync_config_file", _fake_sync_config_file)
    monkeypatch.setattr(
        _config,
        "get_config_manager",
        lambda: SimpleNamespace(
            reload=lambda: calls.append(("reload", None, None)),
        ),
    )
    monkeypatch.setattr(
        _config, "validate_required_config", _fake_validate_required_config
    )

    response = await _config.sync_config_template_handler(
        cast(web.Request, cast(Any, request))
    )
    payload = _json_payload(response)

    assert payload["success"] is True
    assert payload["preview"] is False
    assert payload["warning"] == "missing required field"
    assert calls == [
        ("sync", True, True),
        ("reload", None, None),
        ("validate", None, None),
    ]


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


async def test_index_handler_applies_launcher_mode_and_initial_view() -> None:
    request = _request(
        query={
            "lang": "en",
            "theme": "dark",
            "view": "app",
            "tab": "logs",
            "client": "native",
        }
    )

    response = await _index.index_handler(cast(web.Request, cast(Any, request)))
    payload_text = cast(web.Response, response).text

    assert payload_text is not None
    assert '"lang": "en"' in payload_text
    assert '"theme": "dark"' in payload_text
    assert '"initial_tab": "logs"' in payload_text
    assert '"launcher_mode": true' in payload_text
    assert (
        '<script id="initial-view" type="application/json">"app"</script>'
        in payload_text
    )


async def test_index_handler_renders_mobile_shell_and_action_toggles() -> None:
    request = _request(query={"view": "app", "tab": "config"})

    response = await _index.index_handler(cast(web.Request, cast(Any, request)))
    payload_text = cast(web.Response, response).text

    assert payload_text is not None
    assert 'id="mobileMenuBtn"' in payload_text
    assert 'id="mobileDrawer"' in payload_text
    assert 'id="mobileNavFooter"' in payload_text
    assert 'id="configMobileActionsToggle"' in payload_text
    assert 'id="logsMobileActionsToggle"' in payload_text


def test_webui_cors_only_allows_trusted_origins(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        webui_app,
        "load_webui_settings",
        lambda: SimpleNamespace(url="127.0.0.1", port=8787),
    )
    trusted_request = cast(
        web.Request,
        cast(Any, DummyRequest(headers={"Origin": "http://127.0.0.1:8787"})),
    )
    trusted_response = web.Response(status=200)
    webui_app._apply_cors_headers(trusted_request, trusted_response)
    assert trusted_response.headers.get("Access-Control-Allow-Origin") == (
        "http://127.0.0.1:8787"
    )
    assert trusted_response.headers.get("Access-Control-Allow-Credentials") == "true"

    loopback_request = cast(
        web.Request,
        cast(Any, DummyRequest(headers={"Origin": "http://localhost:1420"})),
    )
    loopback_response = web.Response(status=200)
    webui_app._apply_cors_headers(loopback_request, loopback_response)
    assert loopback_response.headers.get("Access-Control-Allow-Origin") == (
        "http://localhost:1420"
    )

    untrusted_request = cast(
        web.Request,
        cast(Any, DummyRequest(headers={"Origin": "https://evil.example"})),
    )
    untrusted_response = web.Response(status=200)
    webui_app._apply_cors_headers(untrusted_request, untrusted_response)
    assert "Access-Control-Allow-Origin" not in untrusted_response.headers
    assert "Access-Control-Allow-Credentials" not in untrusted_response.headers


def test_runtime_api_cors_only_allows_trusted_origins(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        runtime_api_helpers,
        "load_webui_settings",
        lambda: SimpleNamespace(url="127.0.0.1", port=8787),
    )
    trusted_request = cast(
        web.Request,
        cast(Any, DummyRequest(headers={"Origin": "tauri://localhost"})),
    )
    trusted_response = web.Response(status=200)
    runtime_api_helpers._apply_cors_headers(trusted_request, trusted_response)
    assert trusted_response.headers.get("Access-Control-Allow-Origin") == (
        "tauri://localhost"
    )
    assert trusted_response.headers.get("Access-Control-Allow-Credentials") == "true"

    loopback_request = cast(
        web.Request,
        cast(Any, DummyRequest(headers={"Origin": "http://localhost:1420"})),
    )
    loopback_response = web.Response(status=200)
    runtime_api_helpers._apply_cors_headers(loopback_request, loopback_response)
    assert loopback_response.headers.get("Access-Control-Allow-Origin") == (
        "http://localhost:1420"
    )

    untrusted_request = cast(
        web.Request,
        cast(Any, DummyRequest(headers={"Origin": "https://evil.example"})),
    )
    untrusted_response = web.Response(status=200)
    runtime_api_helpers._apply_cors_headers(untrusted_request, untrusted_response)
    assert "Access-Control-Allow-Origin" not in untrusted_response.headers
    assert "Access-Control-Allow-Credentials" not in untrusted_response.headers


def test_get_refresh_token_prefers_cookie_when_payload_missing() -> None:
    request = cast(
        web.Request,
        cast(Any, DummyRequest(cookies={_shared.TOKEN_COOKIE: "refresh-cookie"})),
    )
    assert _shared.get_refresh_token(request, payload={}) == "refresh-cookie"


async def test_management_meme_update_handler_returns_400_on_invalid_json(
    monkeypatch: Any,
) -> None:
    class _BadJsonRequest(SimpleNamespace):
        async def json(self) -> dict[str, object]:
            raise json.JSONDecodeError("bad", "x", 0)

    monkeypatch.setattr(_memes, "check_auth", lambda _request: True)
    request = cast(
        web.Request,
        cast(
            Any,
            _BadJsonRequest(
                headers={},
                cookies={},
                query={},
                match_info={"uid": "pic_demo"},
                app=_request().app,
            ),
        ),
    )

    response = await _memes.management_meme_update_handler(request)
    payload = _json_payload(response)

    assert cast(web.Response, response).status == 400
    assert payload["error"] == "Invalid JSON payload"


async def test_management_meme_blob_handler_url_encodes_uid(
    monkeypatch: Any,
) -> None:
    captured: dict[str, str] = {}

    async def _fake_proxy_binary(request: web.Request, path: str) -> web.Response:
        _ = request
        captured["path"] = path
        return web.json_response({"ok": True})

    monkeypatch.setattr(_memes, "check_auth", lambda _request: True)
    monkeypatch.setattr(_memes, "_proxy_binary", _fake_proxy_binary)

    request = cast(
        web.Request,
        cast(
            Any,
            SimpleNamespace(
                headers={},
                cookies={},
                query={},
                match_info={"uid": "pic a/b?"},
                app=_request().app,
            ),
        ),
    )

    response = await _memes.management_meme_blob_handler(request)
    payload = _json_payload(response)

    assert payload["ok"] is True
    assert captured["path"] == "/api/v1/memes/pic%20a%2Fb%3F/blob"
