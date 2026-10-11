from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from Undefined.config import Config
from Undefined.config.manager import ConfigManager
from Undefined.webui import app as webui_app
from Undefined.webui.routes import _auth
from Undefined.webui.routes._shared import SESSION_STORE_APP_KEY, SETTINGS_APP_KEY


def _manager_and_app(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, ConfigManager, web.Application]:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("Undefined.config.config_class._load_env", lambda: None)
    path = tmp_path / "config.toml"
    path.write_text('[webui]\npassword="private-old"\n', encoding="utf-8")
    manager = ConfigManager(path)
    manager.load(strict=False)
    monkeypatch.setattr(webui_app, "get_config_manager", lambda: manager)
    return path, manager, webui_app.create_app()


def test_management_invalid_reload_preserves_cached_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path, manager, app = _manager_and_app(tmp_path, monkeypatch)
    previous = app[SETTINGS_APP_KEY]
    path.write_text("[webui\n", encoding="utf-8")
    with pytest.raises(ValueError):
        manager.reload(strict=False)
    assert app[SETTINGS_APP_KEY] is previous
    assert previous.password == "private-old"
    assert not previous.using_default_password


@pytest.mark.parametrize("external_write", ["malformed", "deleted"])
def test_management_reload_uses_validated_snapshot_after_external_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, external_write: str
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("Undefined.config.config_class._load_env", lambda: None)
    path = tmp_path / "config.toml"
    path.write_text('[webui]\npassword="private-old"\n', encoding="utf-8")
    manager = ConfigManager(path)
    config = manager.load(strict=False)
    monkeypatch.setattr(webui_app, "get_config_manager", lambda: manager)

    def _write_after_config_loaded(_config: Config, _changes: dict[str, Any]) -> None:
        if external_write == "malformed":
            path.write_text("[webui\n", encoding="utf-8")
        else:
            path.unlink()

    # 模拟另一进程在已验证读取后、WebUI 订阅回调前编辑文件。
    manager.subscribe(_write_after_config_loaded)
    app = webui_app.create_app()
    valid = '[webui]\npassword="private-new"\nport=18787\ncheck_updates=false\n'
    path.write_text(valid, encoding="utf-8")
    assert manager.reload(strict=False)
    settings = app[SETTINGS_APP_KEY]
    assert settings.password == config.webui_password == "private-new"
    assert settings.port == config.webui_port == 18787
    assert not settings.check_updates
    assert not settings.using_default_password
    assert settings.config_exists

    path.write_text(valid, encoding="utf-8")
    assert manager.reload(strict=False) == {}
    assert app[SETTINGS_APP_KEY].password == "private-new"


@pytest.mark.asyncio
async def test_management_hot_reload_explicit_default_password_rejects_login(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path, manager, app = _manager_and_app(tmp_path, monkeypatch)
    path.write_text('[webui]\npassword="changeme"\n', encoding="utf-8")
    manager.reload(strict=False)
    assert app[SETTINGS_APP_KEY].using_default_password
    request = make_mocked_request("POST", "/api/login", app=app)

    async def _json() -> dict[str, str]:
        return {"password": "changeme"}

    monkeypatch.setattr(request, "json", _json)
    response = await _auth.login_handler(request)
    assert response.status == 403
    payload = cast(web.Response, response).text
    assert payload is not None
    assert '"code": "default_password"' in payload


@pytest.mark.asyncio
async def test_password_change_keeps_validated_settings_after_external_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path, manager, app = _manager_and_app(tmp_path, monkeypatch)
    monkeypatch.setattr(_auth, "get_config_manager", lambda: manager)

    def _corrupt_after_webui_callback(
        _config: Config, _changes: dict[str, Any]
    ) -> None:
        path.write_text("[webui\n", encoding="utf-8")

    manager.subscribe(_corrupt_after_webui_callback)
    sessions = app[SESSION_STORE_APP_KEY]
    token = sessions.create()
    request = make_mocked_request(
        "POST", "/api/password", headers={"X-Auth-Token": token}, app=app
    )

    async def _json() -> dict[str, str]:
        return {"current_password": "private-old", "new_password": "private-new"}

    monkeypatch.setattr(request, "json", _json)
    response = await _auth.password_handler(request)
    assert response.status == 200
    assert path.read_text(encoding="utf-8") == "[webui\n"
    assert app[SETTINGS_APP_KEY].password == "private-new"
    assert not app[SETTINGS_APP_KEY].using_default_password
    assert not sessions.is_valid(token)
