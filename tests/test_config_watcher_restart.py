from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from aiohttp import web

from Undefined.config import Config
from Undefined.config.hot_reload import (
    HotReloadContext,
    _BACKGROUND_TASKS,
    apply_config_updates,
)
from Undefined.config.manager import ConfigManager
from Undefined.webui.core import SessionStore
from Undefined.webui.routes import _config
from Undefined.webui.routes._shared import SESSION_STORE_APP_KEY
from Undefined.webui.utils import config_io


class _Request(SimpleNamespace):
    async def json(self) -> dict[str, Any]:
        return cast(dict[str, Any], self.body)


@pytest.mark.asyncio
@pytest.mark.parametrize("broken_start", [False, True])
async def test_watcher_catches_saves_before_start_and_survives_invalid_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, broken_start: bool
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("Undefined.config.config_class._load_env", lambda: None)
    path = tmp_path / "config.toml"
    path.write_text("[core]\nai_request_max_retries=2\n", encoding="utf-8")
    manager = ConfigManager(path)
    config = manager.load(strict=False)
    applied = asyncio.Event()
    manager.subscribe(lambda _updated, _changes: applied.set())
    path.write_text(
        "[core\n" if broken_start else "[core]\nai_request_max_retries=7\n",
        encoding="utf-8",
    )
    manager.start_hot_reload(interval=0.01, debounce=0.01)
    try:
        if broken_start:
            await asyncio.sleep(0.03)
            assert config.ai_request_max_retries == 2
            assert manager._watch_task is not None and not manager._watch_task.done()
            path.write_text("[core]\nai_request_max_retries=7\n", encoding="utf-8")
        await asyncio.wait_for(applied.wait(), timeout=2)
        assert config.ai_request_max_retries == 7
    finally:
        await manager.stop_hot_reload()


@pytest.mark.asyncio
@pytest.mark.parametrize("change_interval_again", [False, True])
async def test_management_save_during_watcher_restart_reaches_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    change_interval_again: bool,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("Undefined.config.config_class._load_env", lambda: None)
    path = tmp_path / "config.toml"
    path.write_text(
        "[core]\nbot_qq=10001\nsuperadmin_qq=20002\nai_request_max_retries=2\n"
        "[skills]\nhot_reload_interval=0.01\nhot_reload_debounce=0.01\n",
        encoding="utf-8",
    )
    runtime = ConfigManager(path)
    current = runtime.load(strict=False)
    management = ConfigManager(path)
    management.load(strict=False)
    updates: list[int] = []
    applied = asyncio.Event()

    def update_retries(value: int) -> None:
        updates.append(value)
        applied.set()

    registry = SimpleNamespace(
        stop_hot_reload=AsyncMock(), start_hot_reload=lambda **_: None
    )
    context = HotReloadContext(
        ai_client=cast(
            Any, SimpleNamespace(tool_registry=registry, agent_registry=registry)
        ),
        queue_manager=cast(Any, SimpleNamespace(update_max_retries=update_retries)),
        config_manager=runtime,
        security_service=cast(Any, SimpleNamespace(apply_config=lambda _: None)),
    )

    def on_change(config: Config, changes: dict[str, tuple[Any, Any]]) -> None:
        apply_config_updates(config, changes, context)

    runtime.subscribe(on_change)
    app = web.Application()
    sessions = SessionStore()
    app[SESSION_STORE_APP_KEY] = sessions
    token = sessions.create(kind="access")
    monkeypatch.setattr(_config, "CONFIG_PATH", path)
    monkeypatch.setattr(config_io, "CONFIG_PATH", path)
    monkeypatch.setattr(_config, "get_config_manager", lambda: management)

    async def patch_config(body: dict[str, Any]) -> web.StreamResponse:
        request = cast(
            web.Request,
            _Request(
                body={"patch": body},
                app=app,
                headers={"Authorization": f"Bearer {token}"},
                cookies={},
                query={},
            ),
        )
        return await _config.config_patch_handler(request)

    stopped = asyncio.Event()
    release = asyncio.Event()
    original_stop = runtime.stop_hot_reload

    async def pause_restart(timeout: float | None = 2.0) -> None:
        await original_stop(timeout)
        stopped.set()
        await release.wait()

    monkeypatch.setattr(runtime, "stop_hot_reload", pause_restart)
    runtime.start_hot_reload(interval=0.01, debounce=0.01)
    try:
        await asyncio.sleep(0)
        first = await patch_config({"skills.hot_reload_interval": 0.02})
        assert first.status == 200
        await asyncio.wait_for(stopped.wait(), timeout=2)
        second_patch: dict[str, Any] = {"core.ai_request_max_retries": 7}
        if change_interval_again:
            second_patch["skills.hot_reload_interval"] = 0.03
        second = await patch_config(second_patch)
        assert second.status == 200
        assert current.ai_request_max_retries == 2
        release.set()
        await asyncio.wait_for(applied.wait(), timeout=2)
        assert current.ai_request_max_retries == 7
        assert updates == [7]
        assert management.load(strict=False).ai_request_max_retries == 7
        if _BACKGROUND_TASKS:
            await asyncio.gather(*list(_BACKGROUND_TASKS))
        assert runtime._watch_task is not None and not runtime._watch_task.done()
    finally:
        release.set()
        if _BACKGROUND_TASKS:
            await asyncio.gather(*list(_BACKGROUND_TASKS), return_exceptions=True)
        await original_stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("reload_before_restart_finishes", [False, True])
async def test_overlapping_watcher_restarts_keep_only_latest_listener(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    reload_before_restart_finishes: bool,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("Undefined.config.config_class._load_env", lambda: None)
    path = tmp_path / "config.toml"

    def save_interval(interval: float) -> None:
        path.write_text(
            f"[skills]\nhot_reload_interval={interval}\nhot_reload_debounce=0.0\n",
            encoding="utf-8",
        )

    save_interval(0.05)
    manager = ConfigManager(path)
    manager.load(strict=False)
    registry = SimpleNamespace(
        stop_hot_reload=AsyncMock(), start_hot_reload=lambda **_: None
    )
    context = HotReloadContext(
        ai_client=cast(
            Any, SimpleNamespace(tool_registry=registry, agent_registry=registry)
        ),
        queue_manager=cast(Any, SimpleNamespace()),
        config_manager=manager,
        security_service=cast(Any, SimpleNamespace()),
    )
    manager.subscribe(
        lambda config, changes: apply_config_updates(config, changes, context)
    )
    listeners: list[tuple[asyncio.Task[Any], float]] = []
    original_watch = manager._watch_loop
    original_stop = manager.stop_hot_reload
    stopping = asyncio.Event()

    async def record_watch(interval: float, debounce: float) -> None:
        task = asyncio.current_task()
        assert task is not None
        listeners.append((task, interval))
        await original_watch(interval, debounce)

    async def record_stop(timeout: float | None = 2.0) -> None:
        stopping.set()
        await original_stop(timeout)

    monkeypatch.setattr(manager, "_watch_loop", record_watch)
    monkeypatch.setattr(manager, "stop_hot_reload", record_stop)
    manager.start_hot_reload(interval=0.05, debounce=0.0)
    try:
        await asyncio.sleep(0)
        save_interval(0.08)
        await asyncio.wait_for(stopping.wait(), timeout=2)
        assert manager._watch_stop is not None and manager._watch_stop.is_set()
        save_interval(0.01)
        if reload_before_restart_finishes:
            manager.reload(strict=False)
        async with asyncio.timeout(2):
            while _BACKGROUND_TASKS:
                await asyncio.gather(*list(_BACKGROUND_TASKS))
            await asyncio.sleep(0)
        live = [(task, interval) for task, interval in listeners if not task.done()]
        assert len(live) == 1, [interval for _, interval in live]
        assert live[0][0] is manager._watch_task
        assert live[0][1] == 0.01
    finally:
        await original_stop()
        for task, _ in listeners:
            if not task.done():
                task.cancel()
        await asyncio.gather(*(task for task, _ in listeners), return_exceptions=True)


@pytest.mark.asyncio
async def test_late_concurrent_stop_preserves_restarted_watcher(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("Undefined.config.config_class._load_env", lambda: None)
    path = tmp_path / "config.toml"
    path.write_text("[core]\nai_request_max_retries=2\n", encoding="utf-8")
    manager = ConfigManager(path)
    manager.load(strict=False)
    listeners: list[asyncio.Task[Any]] = []
    original_watch = manager._watch_loop

    async def record_watch(interval: float, debounce: float) -> None:
        task = asyncio.current_task()
        assert task is not None
        listeners.append(task)
        await original_watch(interval, debounce)

    async def stop_then_start() -> None:
        await manager.stop_hot_reload()
        manager.start_hot_reload(interval=0.03, debounce=0.0)

    monkeypatch.setattr(manager, "_watch_loop", record_watch)
    manager.start_hot_reload(interval=0.02, debounce=0.0)
    try:
        await asyncio.sleep(0)
        await asyncio.gather(stop_then_start(), manager.stop_hot_reload())
        await asyncio.sleep(0)
        live = [task for task in listeners if not task.done()]
        assert live == [manager._watch_task]
        assert manager._watch_stop is not None
        assert not manager._watch_stop.is_set()
    finally:
        await manager.stop_hot_reload()
        for task in listeners:
            if not task.done():
                task.cancel()
        await asyncio.gather(*listeners, return_exceptions=True)
