"""Tests for WebUI settings loading.

This module tests WebUI-specific configuration parsing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from Undefined.config import Config
from Undefined.config.webui_settings import WebUISettings, load_webui_settings


def test_load_webui_settings_with_autostart_bot_true(tmp_path: Path) -> None:
    """测试 autostart_bot = true 时正确解析。"""
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        """
[webui]
url = "0.0.0.0"
port = 8080
password = "test123"
autostart_bot = true
""",
        encoding="utf-8",
    )

    settings = load_webui_settings(config_file)

    assert settings.url == "0.0.0.0"
    assert settings.port == 8080
    assert settings.password == "test123"
    assert settings.autostart_bot is True
    assert settings.check_updates is True
    assert settings.using_default_password is False
    assert settings.config_exists is True


def test_load_webui_settings_with_autostart_bot_false(tmp_path: Path) -> None:
    """测试 autostart_bot = false 时正确解析。"""
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        """
[webui]
url = "127.0.0.1"
port = 8787
password = "mypassword"
autostart_bot = false
""",
        encoding="utf-8",
    )

    settings = load_webui_settings(config_file)

    assert settings.url == "127.0.0.1"
    assert settings.port == 8787
    assert settings.password == "mypassword"
    assert settings.autostart_bot is False
    assert settings.check_updates is True
    assert settings.using_default_password is False
    assert settings.config_exists is True


def test_load_webui_settings_autostart_bot_missing(tmp_path: Path) -> None:
    """测试 autostart_bot 缺失时默认为 false。"""
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        """
[webui]
url = "127.0.0.1"
port = 8787
password = "test"
""",
        encoding="utf-8",
    )

    settings = load_webui_settings(config_file)

    assert settings.autostart_bot is False  # 默认值
    assert settings.check_updates is True
    assert settings.using_default_password is False
    assert settings.config_exists is True


def test_load_webui_settings_autostart_bot_with_default_password(
    tmp_path: Path,
) -> None:
    """测试密码为空时 autostart_bot 仍能正确解析。"""
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        """
[webui]
url = "127.0.0.1"
port = 8787
password = ""
autostart_bot = true
""",
        encoding="utf-8",
    )

    settings = load_webui_settings(config_file)

    assert settings.autostart_bot is True
    assert settings.check_updates is True
    assert settings.using_default_password is True
    assert settings.password == "changeme"


def test_load_webui_settings_autostart_bot_string_true(tmp_path: Path) -> None:
    """测试 autostart_bot 接受字符串 'true'。"""
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        """
[webui]
url = "127.0.0.1"
port = 8787
password = "test"
autostart_bot = "true"
""",
        encoding="utf-8",
    )

    settings = load_webui_settings(config_file)

    assert settings.autostart_bot is True
    assert settings.check_updates is True


def test_load_webui_settings_autostart_bot_numeric(tmp_path: Path) -> None:
    """测试 autostart_bot 接受数值 1/0。"""
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        """
[webui]
url = "127.0.0.1"
port = 8787
password = "test"
autostart_bot = 1
""",
        encoding="utf-8",
    )

    settings = load_webui_settings(config_file)

    assert settings.autostart_bot is True
    assert settings.check_updates is True

    config_file.write_text(
        """
[webui]
url = "127.0.0.1"
port = 8787
password = "test"
autostart_bot = 0
""",
        encoding="utf-8",
    )

    settings = load_webui_settings(config_file)

    assert settings.autostart_bot is False
    assert settings.check_updates is True


def test_load_webui_settings_no_config_file() -> None:
    """测试配置文件不存在时的默认行为。"""
    settings = load_webui_settings(Path("/nonexistent/config.toml"))

    assert settings.url == "127.0.0.1"
    assert settings.port == 8787
    assert settings.password == "changeme"
    assert settings.autostart_bot is False  # 默认值
    assert settings.check_updates is True
    assert settings.using_default_password is True
    assert settings.config_exists is False


def test_load_webui_settings_check_updates_can_be_disabled(tmp_path: Path) -> None:
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        """
[webui]
password = "test"
check_updates = false
""",
        encoding="utf-8",
    )

    settings = load_webui_settings(config_file)

    assert settings.check_updates is False


def test_load_webui_settings_explicit_default_password_stays_disabled(
    tmp_path: Path,
) -> None:
    config_file = tmp_path / "config.toml"
    config_file.write_text('[webui]\npassword="changeme"\n', encoding="utf-8")
    settings = load_webui_settings(config_file)
    assert settings.password == "changeme"
    assert settings.using_default_password is True
    assert settings.config_exists is True


@pytest.mark.parametrize("password", ["private-password", "changeme"])
@pytest.mark.parametrize("config_exists", [False, True])
def test_settings_from_config_preserves_snapshot_metadata(
    password: str, config_exists: bool
) -> None:
    config = Config.from_mapping(
        {
            "webui": {
                "url": "::1",
                "port": 18787,
                "password": password,
                "autostart_bot": True,
                "check_updates": False,
            }
        },
        strict=False,
    )
    settings = WebUISettings.from_config(config, config_exists=config_exists)
    assert settings.url == "::1"
    assert settings.port == 18787
    assert settings.password == password
    assert settings.autostart_bot is True
    assert settings.check_updates is False
    assert settings.using_default_password is (password == "changeme")
    assert settings.config_exists is config_exists
