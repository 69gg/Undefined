"""Tests for WebUI bot autostart functionality.

This module tests the on_startup hook to ensure proper autostart behavior
based on the autostart_bot configuration and pending_bot_autostart marker.
"""

from __future__ import annotations

from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web

from Undefined.config.webui_settings import WebUISettings
from Undefined.webui.app import on_startup
from Undefined.webui.routes._shared import BOT_APP_KEY, SETTINGS_APP_KEY


def _make_app(bot: MagicMock, settings: WebUISettings) -> web.Application:
    """构造仅含 bot 与 settings 的伪 app（on_startup 只做 app[KEY] 访问）。"""
    return cast(
        web.Application,
        {BOT_APP_KEY: bot, SETTINGS_APP_KEY: settings},
    )


def _make_bot() -> MagicMock:
    """创建 mock BotProcessController。"""
    bot = MagicMock()
    bot.start = AsyncMock()
    bot.status = MagicMock(return_value={"running": False})
    return bot


def _make_settings(*, autostart_bot: bool) -> WebUISettings:
    """创建指定 autostart_bot 的配置。"""
    return WebUISettings(
        url="127.0.0.1",
        port=8787,
        password="test",
        autostart_bot=autostart_bot,
        check_updates=True,
        using_default_password=False,
        config_exists=True,
    )


def _set_repo_root(monkeypatch: pytest.MonkeyPatch, repo_root: Path) -> None:
    monkeypatch.setattr(
        "Undefined.webui.app.resolve_repo_root",
        lambda _start_dir: repo_root,
    )


@pytest.fixture(autouse=True)
def _patch_config_manager(monkeypatch: pytest.MonkeyPatch) -> None:
    """统一 mock 配置管理器，避免真实热重载副作用。"""
    manager = MagicMock()
    manager.start_hot_reload = MagicMock()
    monkeypatch.setattr("Undefined.webui.app.get_config_manager", lambda: manager)


@pytest.mark.asyncio
async def test_on_startup_with_autostart_enabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """测试 autostart_bot=true 时调用 bot.start()。"""
    bot = _make_bot()
    app = _make_app(bot, _make_settings(autostart_bot=True))
    _set_repo_root(monkeypatch, tmp_path)

    await on_startup(app)

    bot.start.assert_awaited_once()


@pytest.mark.asyncio
async def test_on_startup_with_autostart_disabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """测试 autostart_bot=false 时不调用 bot.start()。"""
    bot = _make_bot()
    app = _make_app(bot, _make_settings(autostart_bot=False))
    _set_repo_root(monkeypatch, tmp_path)

    await on_startup(app)

    bot.start.assert_not_awaited()


@pytest.mark.asyncio
async def test_on_startup_without_repo_still_honors_autostart(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot = _make_bot()
    app = _make_app(bot, _make_settings(autostart_bot=True))
    monkeypatch.setattr(
        "Undefined.webui.app.resolve_repo_root",
        lambda _start_dir: None,
    )

    await on_startup(app)

    bot.start.assert_awaited_once()


@pytest.mark.asyncio
async def test_on_startup_recovery_marker_takes_priority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """测试 pending_bot_autostart marker 优先于 autostart_bot 配置。"""
    bot = _make_bot()
    # 即使 autostart_bot=False，存在 marker 也应启动 bot
    app = _make_app(bot, _make_settings(autostart_bot=False))

    # 创建 pending_bot_autostart marker 文件
    marker_path = tmp_path / "data" / "cache" / "pending_bot_autostart"
    marker_path.parent.mkdir(parents=True, exist_ok=True)
    marker_path.touch()
    _set_repo_root(monkeypatch, tmp_path)

    await on_startup(app)

    # 1. bot.start() 被调用（通过自动恢复标记）
    bot.start.assert_awaited_once()
    # 2. marker 文件被删除
    assert not marker_path.exists()


@pytest.mark.asyncio
async def test_on_startup_marker_does_not_double_start_with_autostart(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """测试 marker 命中后即 return，不会因 autostart 再次启动（仅启动一次）。"""
    bot = _make_bot()
    # marker 与 autostart 同时存在，应只启动一次
    app = _make_app(bot, _make_settings(autostart_bot=True))

    marker_path = tmp_path / "data" / "cache" / "pending_bot_autostart"
    marker_path.parent.mkdir(parents=True, exist_ok=True)
    marker_path.touch()
    _set_repo_root(monkeypatch, tmp_path)

    await on_startup(app)

    # 只启动一次（marker 分支命中后 return）
    bot.start.assert_awaited_once()


@pytest.mark.asyncio
async def test_on_startup_autostart_failure_does_not_block_webui(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """测试自动启动失败不会阻塞 WebUI 启动。"""
    bot = _make_bot()
    bot.start.side_effect = RuntimeError("Bot start failed")
    app = _make_app(bot, _make_settings(autostart_bot=True))
    _set_repo_root(monkeypatch, tmp_path)

    # 执行启动钩子（不应抛出异常）
    await on_startup(app)

    # 验证 bot.start() 被调用（虽然失败了）
    bot.start.assert_awaited_once()
