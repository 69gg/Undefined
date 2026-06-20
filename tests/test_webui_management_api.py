from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from Undefined.api import _helpers as runtime_api_helpers
from Undefined.changelog import ChangelogEntry
from Undefined.webui import app as webui_app
from Undefined.webui.app import create_app
from Undefined.webui.core import SessionStore
from Undefined.webui.routes import (
    _auth,
    _config,
    _index,
    _logs,
    _memes,
    _runtime,
    _shared,
    _system,
)
from Undefined.webui.routes._shared import (
    REDIRECT_TO_CONFIG_ONCE_APP_KEY,
    SESSION_COOKIE,
    SESSION_STORE_APP_KEY,
    SETTINGS_APP_KEY,
)
from Undefined.utils.paths import WEBUI_FILE_CACHE_DIR


class DummyRequest(SimpleNamespace):
    async def json(self) -> dict[str, object]:
        return dict(getattr(self, "_json", {}))


class DummyMultipartField:
    def __init__(self, chunks: list[bytes], *, filename: str = "file.bin") -> None:
        self.name = "file"
        self.filename = filename
        self._chunks = list(chunks)

    async def read_chunk(self) -> bytes:
        if not self._chunks:
            return b""
        return self._chunks.pop(0)


class DummyMultipartRequest(DummyRequest):
    def __init__(self, field: DummyMultipartField | None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._field = field

    async def multipart(self) -> object:
        field = self._field

        class _Reader:
            async def next(self) -> DummyMultipartField | None:
                return field

        return _Reader()


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


def _changelog_entry(version: str, title: str) -> ChangelogEntry:
    return ChangelogEntry(
        version=version,
        title=title,
        summary=f"{title} 摘要",
        changes=(f"{title} 变更一", f"{title} 变更二"),
    )


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


async def test_changelog_handler_defaults_to_current_version(monkeypatch: Any) -> None:
    request = _request()
    monkeypatch.setattr(_system, "check_auth", lambda _request: True)
    monkeypatch.setattr(_system, "__version__", "1.2.3")
    monkeypatch.setattr(
        _system,
        "list_entries",
        lambda: (
            _changelog_entry("v1.3.0", "最新版本"),
            _changelog_entry("v1.2.3", "当前版本"),
        ),
    )

    response = await _system.changelog_handler(cast(web.Request, cast(Any, request)))
    payload = _json_payload(response)

    assert payload["success"] is True
    assert payload["current_version"] == "v1.2.3"
    assert payload["latest_version"] == "v1.3.0"
    assert payload["selected_version"] == "v1.2.3"
    assert cast(dict[str, object], payload["entry"])["title"] == "当前版本"
    assert cast(list[object], payload["versions"])[0] == {
        "version": "v1.3.0",
        "title": "最新版本",
    }


async def test_changelog_handler_selects_requested_version(monkeypatch: Any) -> None:
    request = _request(query={"version": "1.3.0"})
    monkeypatch.setattr(_system, "check_auth", lambda _request: True)
    monkeypatch.setattr(_system, "__version__", "1.2.3")
    monkeypatch.setattr(
        _system,
        "list_entries",
        lambda: (
            _changelog_entry("v1.3.0", "最新版本"),
            _changelog_entry("v1.2.3", "当前版本"),
        ),
    )

    response = await _system.changelog_handler(cast(web.Request, cast(Any, request)))
    payload = _json_payload(response)

    assert payload["selected_version"] == "v1.3.0"
    assert cast(dict[str, object], payload["entry"])["title"] == "最新版本"


async def test_changelog_handler_reports_missing_version(monkeypatch: Any) -> None:
    request = _request(query={"version": "9.9.9"})
    monkeypatch.setattr(_system, "check_auth", lambda _request: True)
    monkeypatch.setattr(_system, "__version__", "1.2.3")
    monkeypatch.setattr(
        _system,
        "list_entries",
        lambda: (_changelog_entry("v1.2.3", "当前版本"),),
    )

    response = await _system.changelog_handler(cast(web.Request, cast(Any, request)))
    payload = _json_payload(response)

    assert cast(web.Response, response).status == 404
    assert payload["success"] is False
    assert payload["error"] == "未找到版本: v9.9.9"


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
    assert ("GET", "/api/v1/management/changelog") in routes
    assert ("GET", "/api/v1/management/runtime/meta") in routes
    assert ("GET", "/api/v1/management/runtime/schedules") in routes
    assert ("POST", "/api/v1/management/runtime/schedules") in routes
    assert ("GET", "/api/v1/management/runtime/schedules/{task_id}") in routes
    assert ("PATCH", "/api/v1/management/runtime/schedules/{task_id}") in routes
    assert ("DELETE", "/api/v1/management/runtime/schedules/{task_id}") in routes
    assert ("POST", "/api/v1/management/config/validate") in routes
    assert ("POST", "/api/v1/management/bot/start") in routes
    assert ("POST", "/api/v1/management/runtime/chat/jobs") in routes
    assert ("GET", "/api/v1/management/runtime/chat/jobs/active") in routes
    assert ("GET", "/api/v1/management/runtime/chat/jobs/{job_id}") in routes
    assert ("GET", "/api/v1/management/runtime/chat/jobs/{job_id}/events") in routes
    assert ("POST", "/api/v1/management/runtime/chat/jobs/{job_id}/cancel") in routes
    assert ("DELETE", "/api/v1/management/runtime/chat/history") in routes
    assert (
        "GET",
        "/api/v1/management/runtime/chat/attachments/capabilities",
    ) in routes
    assert ("POST", "/api/v1/management/runtime/chat/attachments") in routes
    assert (
        "GET",
        "/api/v1/management/runtime/chat/attachments/{attachment_id}",
    ) in routes
    assert (
        "GET",
        "/api/v1/management/runtime/chat/attachments/{attachment_id}/preview",
    ) in routes
    assert ("POST", "/api/v1/management/runtime/chat/files") in routes


def test_management_logs_line_limit_clamps_to_larger_cap() -> None:
    assert (
        _logs._parse_log_lines(cast(web.Request, cast(Any, _request())))
        == _logs.DEFAULT_LOG_TAIL_LINES
    )
    assert (
        _logs._parse_log_lines(
            cast(web.Request, cast(Any, _request(query={"lines": "50000"})))
        )
        == _logs.MAX_LOG_TAIL_LINES
    )
    assert (
        _logs._parse_log_lines(
            cast(web.Request, cast(Any, _request(query={"lines": "bad"})))
        )
        == _logs.DEFAULT_LOG_TAIL_LINES
    )


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


async def test_runtime_chat_file_upload_handler_caches_authenticated_file(
    monkeypatch: Any, tmp_path: Path
) -> None:
    monkeypatch.setattr(_runtime, "check_auth", lambda _request: True)
    monkeypatch.chdir(tmp_path)
    field = DummyMultipartField([b"hello", b" world"], filename="../note.txt")
    request = DummyMultipartRequest(
        field,
        headers={},
        cookies={},
        query={},
        app={},
        remote="127.0.0.1",
        scheme="http",
        host="127.0.0.1:8787",
        transport=None,
    )

    response = await _runtime.runtime_chat_file_upload_handler(
        cast(web.Request, cast(Any, request))
    )
    payload = _json_payload(response)

    assert cast(web.Response, response).status == 200
    assert isinstance(payload["id"], str)
    assert str(payload["id"]).isalnum()
    assert payload["name"] == "note.txt"
    assert payload["size"] == 11
    cached_dir = tmp_path / WEBUI_FILE_CACHE_DIR / str(payload["id"])
    cached_files = list(cached_dir.iterdir())
    assert len(cached_files) == 1
    cached_file = cached_files[0]
    assert cached_file.name != "note.txt"
    assert cached_file.name.startswith("file_")
    assert cached_file.read_bytes() == b"hello world"


async def test_runtime_chat_file_upload_handler_requires_auth(monkeypatch: Any) -> None:
    monkeypatch.setattr(_runtime, "check_auth", lambda _request: False)
    request = DummyMultipartRequest(
        None,
        headers={},
        cookies={},
        query={},
        app={},
        remote="127.0.0.1",
        scheme="http",
        host="127.0.0.1:8787",
        transport=None,
    )

    response = await _runtime.runtime_chat_file_upload_handler(
        cast(web.Request, cast(Any, request))
    )

    assert cast(web.Response, response).status == 401


async def test_index_handler_renders_schedules_tab() -> None:
    request = _request(query={"view": "app", "tab": "schedules"})

    response = await _index.index_handler(cast(web.Request, cast(Any, request)))
    payload_text = cast(web.Response, response).text

    assert payload_text is not None
    assert 'id="tab-schedules"' in payload_text
    assert 'data-tab="schedules"' in payload_text
    assert '<script src="/static/js/schedules.js"></script>' in payload_text


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


async def test_management_schedule_create_requires_auth(
    monkeypatch: Any,
) -> None:
    called = False

    async def _fake_proxy_runtime(**_kwargs: Any) -> web.Response:
        nonlocal called
        called = True
        return web.json_response({"ok": True})

    monkeypatch.setattr(_runtime, "check_auth", lambda _request: False)
    monkeypatch.setattr(_runtime, "_proxy_runtime", _fake_proxy_runtime)

    response = await _runtime.runtime_schedules_create_handler(
        cast(web.Request, cast(Any, _request(json_body={"task_id": "task_demo"})))
    )
    payload = _json_payload(response)

    assert cast(web.Response, response).status == 401
    assert payload["error"] == "Unauthorized"
    assert called is False


async def test_management_schedule_update_returns_400_on_invalid_json(
    monkeypatch: Any,
) -> None:
    class _BadJsonRequest(SimpleNamespace):
        async def json(self) -> dict[str, object]:
            raise json.JSONDecodeError("bad", "x", 0)

    monkeypatch.setattr(_runtime, "check_auth", lambda _request: True)
    request = cast(
        web.Request,
        cast(
            Any,
            _BadJsonRequest(
                headers={},
                cookies={},
                query={},
                match_info={"task_id": "task_demo"},
                app=_request().app,
            ),
        ),
    )

    response = await _runtime.runtime_schedule_update_handler(request)
    payload = _json_payload(response)

    assert cast(web.Response, response).status == 400
    assert payload["error"] == "Invalid JSON payload"


async def test_management_schedule_detail_url_encodes_task_id(
    monkeypatch: Any,
) -> None:
    captured: dict[str, str] = {}

    async def _fake_proxy_runtime(**kwargs: Any) -> web.Response:
        captured["method"] = str(kwargs["method"])
        captured["path"] = str(kwargs["path"])
        return web.json_response({"ok": True})

    monkeypatch.setattr(_runtime, "check_auth", lambda _request: True)
    monkeypatch.setattr(_runtime, "_proxy_runtime", _fake_proxy_runtime)

    request = cast(
        web.Request,
        cast(
            Any,
            SimpleNamespace(
                headers={},
                cookies={},
                query={},
                match_info={"task_id": "task a/b?"},
                app=_request().app,
            ),
        ),
    )

    response = await _runtime.runtime_schedule_detail_handler(request)
    payload = _json_payload(response)

    assert payload["ok"] is True
    assert captured == {
        "method": "GET",
        "path": "/api/v1/schedules/task%20a%2Fb%3F",
    }


async def test_management_schedule_create_proxies_json_payload(
    monkeypatch: Any,
) -> None:
    captured: dict[str, Any] = {}

    async def _fake_proxy_runtime(**kwargs: Any) -> web.Response:
        captured.update(kwargs)
        return web.json_response({"ok": True}, status=201)

    monkeypatch.setattr(_runtime, "check_auth", lambda _request: True)
    monkeypatch.setattr(_runtime, "_proxy_runtime", _fake_proxy_runtime)

    response = await _runtime.runtime_schedules_create_handler(
        cast(
            web.Request,
            cast(
                Any,
                _request(
                    json_body={
                        "task_id": "task_demo",
                        "cron_expression": "0 9 * * *",
                    }
                ),
            ),
        )
    )
    payload = _json_payload(response)

    assert cast(web.Response, response).status == 201
    assert payload["ok"] is True
    assert captured["method"] == "POST"
    assert captured["path"] == "/api/v1/schedules"
    assert captured["payload"] == {
        "task_id": "task_demo",
        "cron_expression": "0 9 * * *",
    }


async def test_runtime_chat_job_proxy_routes_require_management_auth() -> None:
    request = cast(
        web.Request,
        cast(
            Any,
            SimpleNamespace(
                headers={},
                cookies={},
                query={},
                match_info={"job_id": "job_1"},
                app=_request().app,
            ),
        ),
    )

    handlers = [
        _runtime.runtime_chat_conversations_handler,
        _runtime.runtime_chat_conversation_create_handler,
        _runtime.runtime_chat_conversation_update_handler,
        _runtime.runtime_chat_conversation_delete_handler,
        _runtime.runtime_chat_history_clear_handler,
        _runtime.runtime_chat_job_create_handler,
        _runtime.runtime_chat_job_active_handler,
        _runtime.runtime_chat_job_detail_handler,
        _runtime.runtime_chat_job_events_handler,
        _runtime.runtime_chat_job_cancel_handler,
    ]
    for handler in handlers:
        response = await handler(request)
        assert cast(web.Response, response).status == 401


async def test_runtime_chat_job_proxy_json_injects_runtime_api_key(
    monkeypatch: Any,
) -> None:
    captured: dict[str, Any] = {}

    async def _fake_proxy_runtime(**kwargs: Any) -> web.Response:
        captured.update(kwargs)
        return web.json_response({"ok": True})

    monkeypatch.setattr(_runtime, "_proxy_runtime", _fake_proxy_runtime)
    monkeypatch.setattr(_runtime, "check_auth", lambda _request: True)
    request = cast(
        web.Request,
        cast(
            Any,
            SimpleNamespace(
                headers={"Accept": "application/json"},
                cookies={},
                query={"after": "7", "format": "json"},
                match_info={"job_id": "job /secret"},
                app=_request().app,
            ),
        ),
    )

    response = await _runtime.runtime_chat_job_events_handler(request)
    payload = _json_payload(response)

    assert payload["ok"] is True
    assert captured["method"] == "GET"
    assert captured["path"] == "/api/v1/chat/jobs/job%20%2Fsecret/events"
    assert captured["params"]["after"] == "7"
    assert captured["timeout_seconds"] == 20.0


async def test_runtime_chat_job_proxy_preserves_structured_message(
    monkeypatch: Any,
) -> None:
    captured: dict[str, Any] = {}

    async def _fake_proxy_runtime(**kwargs: Any) -> web.Response:
        captured.update(kwargs)
        return web.json_response({"job_id": "job-1"})

    monkeypatch.setattr(_runtime, "_proxy_runtime", _fake_proxy_runtime)
    monkeypatch.setattr(_runtime, "check_auth", lambda _request: True)
    request = _request(
        json_body={
            "conversation_id": "conv-1",
            "message": {
                "text": "分析附件",
                "attachment_ids": ["att-1"],
                "references": [{"message_id": "msg-1", "quote": "引用"}],
            },
        }
    )

    response = await _runtime.runtime_chat_job_create_handler(
        cast(web.Request, cast(Any, request))
    )
    payload = _json_payload(response)

    assert payload["job_id"] == "job-1"
    assert captured["method"] == "POST"
    assert captured["path"] == "/api/v1/chat/jobs"
    assert captured["payload"] == {
        "conversation_id": "conv-1",
        "message": {
            "text": "分析附件",
            "attachment_ids": ["att-1"],
            "references": [{"message_id": "msg-1", "quote": "引用"}],
        },
    }


async def test_runtime_chat_job_proxy_forwards_retry_reuse_flag(
    monkeypatch: Any,
) -> None:
    captured: dict[str, Any] = {}

    async def _fake_proxy_runtime(**kwargs: Any) -> web.Response:
        captured.update(kwargs)
        return web.json_response({"job_id": "job-retry"})

    monkeypatch.setattr(_runtime, "_proxy_runtime", _fake_proxy_runtime)
    monkeypatch.setattr(_runtime, "check_auth", lambda _request: True)
    request = _request(
        json_body={
            "conversation_id": "conv-1",
            "message": "重新生成",
            "reuse_previous_user_message": True,
        }
    )

    response = await _runtime.runtime_chat_job_create_handler(
        cast(web.Request, cast(Any, request))
    )
    payload = _json_payload(response)

    assert payload["job_id"] == "job-retry"
    assert captured["payload"] == {
        "conversation_id": "conv-1",
        "message": "重新生成",
        "reuse_previous_user_message": True,
    }


async def test_runtime_chat_attachment_capabilities_proxy(
    monkeypatch: Any,
) -> None:
    captured: dict[str, Any] = {}

    async def _fake_proxy_runtime(**kwargs: Any) -> web.Response:
        captured.update(kwargs)
        return web.json_response({"multipart_field": "file"})

    monkeypatch.setattr(_runtime, "_proxy_runtime", _fake_proxy_runtime)
    monkeypatch.setattr(_runtime, "check_auth", lambda _request: True)
    request = _request()

    response = await _runtime.runtime_chat_attachment_capabilities_handler(
        cast(web.Request, cast(Any, request))
    )
    payload = _json_payload(response)

    assert payload["multipart_field"] == "file"
    assert captured["method"] == "GET"
    assert captured["path"] == "/api/v1/chat/attachments/capabilities"


async def test_runtime_chat_attachment_upload_proxy(
    monkeypatch: Any,
) -> None:
    captured: dict[str, Any] = {}

    async def _fake_proxy_runtime_multipart_file(
        request: web.Request,
        **kwargs: Any,
    ) -> web.Response:
        captured["request"] = request
        captured.update(kwargs)
        return web.json_response({"attachment": {"id": "att-1"}}, status=201)

    monkeypatch.setattr(
        _runtime,
        "_proxy_runtime_multipart_file",
        _fake_proxy_runtime_multipart_file,
    )
    monkeypatch.setattr(_runtime, "check_auth", lambda _request: True)
    request = DummyMultipartRequest(DummyMultipartField([b"data"]))

    response = await _runtime.runtime_chat_attachment_upload_handler(
        cast(web.Request, cast(Any, request))
    )
    payload = _json_payload(response)

    assert cast(web.Response, response).status == 201
    assert cast(dict[str, object], payload["attachment"])["id"] == "att-1"
    assert captured["path"] == "/api/v1/chat/attachments"
    assert captured["request"] is request


async def test_runtime_chat_attachment_download_and_preview_proxy(
    monkeypatch: Any,
) -> None:
    captured: list[dict[str, Any]] = []

    async def _fake_proxy_runtime_binary(**kwargs: Any) -> web.Response:
        captured.append(dict(kwargs))
        return web.Response(body=b"PNG", content_type="image/png")

    monkeypatch.setattr(_runtime, "_proxy_runtime_binary", _fake_proxy_runtime_binary)
    monkeypatch.setattr(_runtime, "check_auth", lambda _request: True)
    download_request = cast(
        web.Request,
        cast(
            Any,
            SimpleNamespace(
                headers={},
                cookies={},
                query={},
                match_info={"attachment_id": "att /1"},
                app=_request().app,
            ),
        ),
    )
    preview_request = cast(
        web.Request,
        cast(
            Any,
            SimpleNamespace(
                headers={},
                cookies={},
                query={},
                match_info={"attachment_id": "att /1"},
                app=_request().app,
            ),
        ),
    )

    download_response = await _runtime.runtime_chat_attachment_download_handler(
        download_request
    )
    preview_response = await _runtime.runtime_chat_attachment_preview_handler(
        preview_request
    )

    assert cast(web.Response, download_response).body == b"PNG"
    assert cast(web.Response, preview_response).body == b"PNG"
    assert captured == [
        {
            "method": "GET",
            "path": "/api/v1/chat/attachments/att%20%2F1",
            "timeout_seconds": 60.0,
        },
        {
            "method": "GET",
            "path": "/api/v1/chat/attachments/att%20%2F1/preview",
            "timeout_seconds": 60.0,
        },
    ]


def test_management_api_docs_describe_native_chat_contract() -> None:
    docs_path = Path(__file__).resolve().parents[1] / "docs" / "management-api.md"
    text = docs_path.read_text(encoding="utf-8")

    assert "全局 job 互斥" not in text
    assert "CQ:file" not in text
    assert "attachment_ids" in text
    assert "同一会话" in text


async def test_runtime_chat_job_proxy_sse_uses_stream_proxy(
    monkeypatch: Any,
) -> None:
    captured: dict[str, Any] = {}

    async def _fake_proxy_runtime_stream(
        request: web.Request,
        **kwargs: Any,
    ) -> web.Response:
        captured["accept"] = request.headers.get("Accept")
        captured.update(kwargs)
        return web.json_response({"stream": True})

    monkeypatch.setattr(_runtime, "_proxy_runtime_stream", _fake_proxy_runtime_stream)
    monkeypatch.setattr(_runtime, "check_auth", lambda _request: True)
    monkeypatch.setattr(_runtime, "_chat_proxy_timeout_seconds", lambda: 123.0)
    request = cast(
        web.Request,
        cast(
            Any,
            SimpleNamespace(
                headers={"Accept": "text/event-stream"},
                cookies={},
                query={"after": "0"},
                match_info={"job_id": "job_1"},
                app=_request().app,
            ),
        ),
    )

    response = await _runtime.runtime_chat_job_events_handler(request)
    payload = _json_payload(response)

    assert payload["stream"] is True
    assert captured["method"] == "GET"
    assert captured["path"] == "/api/v1/chat/jobs/job_1/events"
    assert captured["params"]["after"] == "0"
    assert captured["timeout_seconds"] == 123.0
    assert captured["accept"] == "text/event-stream"


async def test_proxy_runtime_injects_runtime_api_key(monkeypatch: Any) -> None:
    captured: dict[str, Any] = {}

    class _FakeResponse:
        status = 200
        headers = {"Content-Type": "application/json"}
        content_type = "application/json"
        charset = "utf-8"

        async def __aenter__(self) -> _FakeResponse:
            return self

        async def __aexit__(self, *_args: Any) -> None:
            return None

        async def text(self) -> str:
            return '{"ok": true}'

    class _FakeSession:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            _ = args, kwargs

        async def __aenter__(self) -> _FakeSession:
            return self

        async def __aexit__(self, *_args: Any) -> None:
            return None

        def request(self, **kwargs: Any) -> _FakeResponse:
            captured.update(kwargs)
            return _FakeResponse()

    monkeypatch.setattr(
        _runtime,
        "get_config",
        lambda strict=False: SimpleNamespace(
            api=SimpleNamespace(
                enabled=True,
                loopback_url="http://127.0.0.1:8788",
                auth_key="runtime-secret",
            )
        ),
    )
    monkeypatch.setattr(_runtime, "ClientSession", _FakeSession)

    response = await _runtime._proxy_runtime(method="GET", path="/api/v1/chat/jobs")
    payload = _json_payload(response)

    assert payload["ok"] is True
    assert captured["headers"] == {"X-Undefined-API-Key": "runtime-secret"}


async def test_static_assets_get_no_cache_revalidation_header() -> None:
    async def _handler(_request: web.Request) -> web.StreamResponse:
        return web.Response(text="asset")

    request = make_mocked_request("GET", "/static/js/runtime.js")
    response = await webui_app.security_headers_middleware(request, _handler)

    # 静态资源强制按 ETag 重新校验，避免前端更新后被强缓存挡住
    assert response.headers["Cache-Control"] == "no-cache"


async def test_security_headers_csp_allows_blob_image_previews() -> None:
    async def _handler(_request: web.Request) -> web.StreamResponse:
        return web.Response(text="page")

    request = make_mocked_request("GET", "/")
    response = await webui_app.security_headers_middleware(request, _handler)

    assert "img-src 'self' data: blob:;" in response.headers["Content-Security-Policy"]


async def test_non_static_responses_have_no_explicit_cache_control() -> None:
    async def _handler(_request: web.Request) -> web.StreamResponse:
        return web.Response(text="page")

    request = make_mocked_request("GET", "/api/v1/management/health")
    response = await webui_app.security_headers_middleware(request, _handler)

    assert "Cache-Control" not in response.headers
