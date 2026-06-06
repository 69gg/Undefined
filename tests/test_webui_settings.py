"""Tests for WebUI settings loading."""

from __future__ import annotations

from pathlib import Path

from Undefined.config.webui_settings import load_webui_settings


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


def test_load_webui_settings_no_config_file() -> None:
    """测试配置文件不存在时的默认行为。"""
    settings = load_webui_settings(Path("/nonexistent/config.toml"))

    assert settings.url == "127.0.0.1"
    assert settings.port == 8787
    assert settings.password == "changeme"
    assert settings.autostart_bot is False  # 默认值
    assert settings.using_default_password is True
    assert settings.config_exists is False
