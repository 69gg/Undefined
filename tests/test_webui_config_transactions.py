from __future__ import annotations

import asyncio
import json
import os
import threading
import tomllib
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from aiohttp import web

from Undefined.config import WebUISettings
from Undefined.config.manager import ConfigManager
from Undefined.utils import io as async_io
from Undefined.utils.file_lock import FileLock
from Undefined.webui.core import SessionStore
from Undefined.webui.routes import _auth, _config
from Undefined.webui.routes._shared import SESSION_STORE_APP_KEY, SETTINGS_APP_KEY
from Undefined.webui.utils import config_io, config_sync


class ConfigRequest(SimpleNamespace):
    async def json(self) -> dict[str, Any]:
        return cast(dict[str, Any], self.body)


@dataclass
class ConfigTransactionFixture:
    path: Path
    example: Path
    backups: Path
    manager: ConfigManager
    app: web.Application
    sessions: SessionStore

    def request(self, body: dict[str, Any] | None = None) -> web.Request:
        return cast(
            web.Request,
            cast(Any, ConfigRequest(body=body or {}, app=self.app, query={})),
        )


@pytest.fixture
def transaction_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> ConfigTransactionFixture:
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "config.toml"
    example = tmp_path / "config.toml.example"
    backups = tmp_path / "backups"
    backups.mkdir()
    path.write_text(
        "[core]\nbot_qq=10001\nsuperadmin_qq=20002\n"
        '[api]\nport=11111\n[webui]\npassword="previous-secret"\n',
        encoding="utf-8",
    )
    example.write_text(
        "[core]\nbot_qq=0\nsuperadmin_qq=0\n[api]\nport=8788\n"
        '[webui]\npassword="changeme"\nstop_timeout_seconds=3\n',
        encoding="utf-8",
    )
    (backups / "config_fixture.toml").write_text(
        path.read_text().replace("11111", "33333"), encoding="utf-8"
    )
    manager = ConfigManager(path)
    config = manager.load(strict=False)
    app = web.Application()
    sessions = SessionStore()
    app[SETTINGS_APP_KEY] = WebUISettings.from_config(config, config_exists=True)
    app[SESSION_STORE_APP_KEY] = sessions
    for module in (_config, _auth, config_io):
        monkeypatch.setattr(module, "CONFIG_PATH", path)
    for module in (_config, _auth):
        monkeypatch.setattr(module, "get_config_manager", lambda: manager)
        monkeypatch.setattr(module, "check_auth", lambda _request: True)
    monkeypatch.setattr(_config, "_BACKUP_DIR", backups)
    monkeypatch.setattr(_config, "validate_required_config", lambda: (True, "OK"))

    def sync(*, prune: bool, write: bool) -> config_sync.ConfigTemplateSyncResult:
        return config_sync.sync_config_file(
            config_path=path, example_path=example, prune=prune, write=write
        )

    monkeypatch.setattr(_config, "sync_config_file", sync)
    return ConfigTransactionFixture(path, example, backups, manager, app, sessions)


async def _wait_thread_event(event: threading.Event) -> None:
    assert await asyncio.wait_for(asyncio.to_thread(event.wait, 2), timeout=3)


@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint", ["save", "patch", "restore", "sync", "password"])
async def test_config_request_repeated_cancellation_finishes_write_and_main_loop_reload(
    transaction_config: ConfigTransactionFixture,
    monkeypatch: pytest.MonkeyPatch,
    endpoint: str,
) -> None:
    fixture = transaction_config
    loop = asyncio.get_running_loop()
    reloaded_on: list[asyncio.AbstractEventLoop] = []

    def on_reload(_config_value: Any, _changes: Any) -> None:
        reloaded_on.append(asyncio.get_running_loop())

    fixture.manager.subscribe(on_reload)
    session = fixture.sessions.create()
    tokens = fixture.sessions.issue_auth_tokens()
    entered = threading.Event()
    release = threading.Event()
    original_write = async_io.write_text_sync

    def blocked_write(
        file_path: Path | str, content: str, use_lock: bool = True
    ) -> None:
        if Path(file_path) == fixture.path:
            entered.set()
            assert release.wait(3), "test did not release configuration write"
        original_write(file_path, content, use_lock)

    monkeypatch.setattr(async_io, "write_text_sync", blocked_write)
    monkeypatch.setattr(config_sync, "write_text_sync", blocked_write)
    if endpoint == "save":
        operation = _config.save_config_handler(
            fixture.request(
                {"content": fixture.path.read_text().replace("11111", "22222")}
            )
        )
    elif endpoint == "patch":
        operation = _config.config_patch_handler(
            fixture.request({"patch": {"api.port": 22222}})
        )
    elif endpoint == "restore":
        operation = _config.config_restore_handler(
            fixture.request({"name": "config_fixture.toml"})
        )
    elif endpoint == "sync":
        operation = _config.sync_config_template_handler(fixture.request())
    else:
        operation = _auth.password_handler(
            fixture.request(
                {
                    "current_password": "previous-secret",
                    "new_password": "updated-secret",
                }
            )
        )

    async def perform_request() -> web.StreamResponse:
        return await operation

    task = asyncio.create_task(perform_request())
    try:
        await _wait_thread_event(entered)
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=3)
        parsed = tomllib.loads(fixture.path.read_text())
        assert reloaded_on == [loop]
        loaded = fixture.manager.load(strict=False)
        assert loaded.api.port == parsed["api"]["port"]
        if endpoint in {"save", "patch"}:
            assert loaded.api.port == 22222
        elif endpoint == "restore":
            assert loaded.api.port == 33333
        elif endpoint == "sync":
            assert parsed["webui"]["stop_timeout_seconds"] == 3
        else:
            assert parsed["webui"]["password"] == "updated-secret"
            assert fixture.app[SETTINGS_APP_KEY].password == "updated-secret"
            assert not fixture.sessions.is_valid(session)
            assert not fixture.sessions.is_valid(str(tokens["access_token"]))
            assert not fixture.sessions.is_valid(str(tokens["refresh_token"]))
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("first_operation", ["sync", "patch"])
async def test_template_sync_and_patch_preserve_both_changes_in_either_order(
    transaction_config: ConfigTransactionFixture,
    monkeypatch: pytest.MonkeyPatch,
    first_operation: str,
) -> None:
    fixture = transaction_config
    first_write_entered = threading.Event()
    release_first_write = threading.Event()
    second_lock_attempted = threading.Event()
    original_write = async_io.write_text_sync
    original_lock = config_io.config_write_lock
    thread_lock = threading.Lock()
    lock_count = 0
    write_count = 0

    def tracked_lock(path: Path) -> Any:
        nonlocal lock_count
        with thread_lock:
            lock_count += 1
            if lock_count == 2:
                second_lock_attempted.set()
        return original_lock(path)

    def blocked_write(
        file_path: Path | str, content: str, use_lock: bool = True
    ) -> None:
        nonlocal write_count
        with thread_lock:
            write_count += 1
            first = write_count == 1
        if first:
            first_write_entered.set()
            assert release_first_write.wait(3), "test did not release first write"
        original_write(file_path, content, use_lock)

    monkeypatch.setattr(async_io, "write_text_sync", blocked_write)
    monkeypatch.setattr(config_sync, "write_text_sync", blocked_write)
    monkeypatch.setattr(_config, "config_write_lock", tracked_lock)
    monkeypatch.setattr(config_sync, "config_write_lock", tracked_lock)

    async def sync() -> Any:
        return await _config.sync_config_template_handler(fixture.request())

    async def patch() -> Any:
        return await _config.config_patch_handler(
            fixture.request({"patch": {"api.port": 22222}})
        )

    first = asyncio.create_task(sync() if first_operation == "sync" else patch())
    second: asyncio.Task[Any] | None = None
    try:
        await _wait_thread_event(first_write_entered)
        second = asyncio.create_task(patch() if first_operation == "sync" else sync())
        await _wait_thread_event(second_lock_attempted)
        assert not second.done()
        release_first_write.set()
        responses = await asyncio.wait_for(asyncio.gather(first, second), timeout=3)
        assert [response.status for response in responses] == [200, 200]
        parsed = tomllib.loads(fixture.path.read_text())
        assert parsed["api"]["port"] == 22222
        assert parsed["webui"]["stop_timeout_seconds"] == 3
        assert fixture.manager.load(strict=False).api.port == 22222
    finally:
        release_first_write.set()
        await asyncio.gather(
            first, *([second] if second is not None else []), return_exceptions=True
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("reader", ["history", "restore"])
@pytest.mark.parametrize("first_operation", ["read", "patch"])
async def test_backup_reads_are_serialized_with_actual_backup_trimming(
    transaction_config: ConfigTransactionFixture,
    monkeypatch: pytest.MonkeyPatch,
    reader: str,
    first_operation: str,
) -> None:
    fixture = transaction_config
    selected_backup = fixture.backups / "config_fixture.toml"
    os.utime(selected_backup, ns=(1, 1))
    monkeypatch.setattr(_config, "_MAX_BACKUPS", 1)
    first_locked = threading.Event()
    release_first = threading.Event()
    second_attempted = threading.Event()
    counter_lock = threading.Lock()
    lock_count = 0
    loop_thread = threading.get_ident()
    original_lock = config_io.config_write_lock

    class PausingConfigLock:
        def __init__(self, lock: FileLock, first: bool) -> None:
            self.lock = lock
            self.first = first

        def __enter__(self) -> PausingConfigLock:
            self.lock.__enter__()
            if self.first:
                first_locked.set()
                assert release_first.wait(3), "test did not release config lock"
            return self

        def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
            self.lock.__exit__(exc_type, exc, tb)

    def tracked_lock(path: Path) -> PausingConfigLock:
        nonlocal lock_count
        assert threading.get_ident() != loop_thread
        with counter_lock:
            lock_count += 1
            first = lock_count == 1
            if lock_count == 2:
                second_attempted.set()
        return PausingConfigLock(original_lock(path), first)

    monkeypatch.setattr(_config, "config_write_lock", tracked_lock)

    async def read_backup() -> web.StreamResponse:
        if reader == "history":
            return await _config.config_history_handler(fixture.request())
        return await _config.config_restore_handler(
            fixture.request({"name": selected_backup.name})
        )

    async def patch() -> web.StreamResponse:
        return await _config.config_patch_handler(
            fixture.request({"patch": {"api.port": 22222}})
        )

    first = asyncio.create_task(read_backup() if first_operation == "read" else patch())
    second: asyncio.Task[web.StreamResponse] | None = None
    try:
        await _wait_thread_event(first_locked)
        second = asyncio.create_task(
            patch() if first_operation == "read" else read_backup()
        )
        await _wait_thread_event(second_attempted)
        assert not second.done()
        release_first.set()
        first_response, second_response = await asyncio.wait_for(
            asyncio.gather(first, second), timeout=3
        )
        read_response = first_response if first_operation == "read" else second_response
        patch_response = (
            first_response if first_operation == "patch" else second_response
        )
        assert patch_response.status == 200
        assert not selected_backup.exists()
        assert len(list(fixture.backups.glob("config_*.toml"))) == 1
        assert tomllib.loads(fixture.path.read_text())["api"]["port"] == 22222
        if reader == "restore" and first_operation == "patch":
            assert read_response.status == 404
        else:
            assert read_response.status == 200
        if reader == "history":
            payload = json.loads(cast(web.Response, read_response).text or "{}")
            names = [backup["name"] for backup in payload["backups"]]
            assert (selected_backup.name in names) is (first_operation == "read")
    finally:
        release_first.set()
        await asyncio.gather(
            first, *([second] if second is not None else []), return_exceptions=True
        )
