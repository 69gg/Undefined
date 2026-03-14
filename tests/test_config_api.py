from __future__ import annotations

from pathlib import Path

from Undefined.config.loader import Config


def _load_config(path: Path, text: str) -> Config:
    path.write_text(text, "utf-8")
    return Config.load(path, strict=False)


def test_api_config_defaults_when_missing(tmp_path: Path) -> None:
    cfg = _load_config(tmp_path / "config.toml", "")
    assert cfg.api.enabled is True
    assert cfg.api.host == "127.0.0.1"
    assert cfg.api.port == 8788
    assert cfg.api.auth_key == "changeme"
    assert cfg.api.openapi_enabled is True
    assert cfg.api.tool_invoke_enabled is False
    assert cfg.api.tool_invoke_expose == "tools+toolsets"
    assert cfg.api.tool_invoke_allowlist == []
    assert cfg.api.tool_invoke_denylist == []
    assert cfg.api.tool_invoke_timeout == 120
    assert cfg.api.tool_invoke_callback_timeout == 10


def test_api_config_custom_values(tmp_path: Path) -> None:
    cfg = _load_config(
        tmp_path / "config.toml",
        """
[api]
enabled = false
host = "0.0.0.0"
port = 9010
auth_key = "secret-key"
openapi_enabled = false
""",
    )
    assert cfg.api.enabled is False
    assert cfg.api.host == "0.0.0.0"
    assert cfg.api.port == 9010
    assert cfg.api.auth_key == "secret-key"
    assert cfg.api.openapi_enabled is False


def test_api_config_invalid_values_fallback(tmp_path: Path) -> None:
    cfg = _load_config(
        tmp_path / "config.toml",
        """
[api]
port = 99999
auth_key = ""
""",
    )
    assert cfg.api.port == 8788
    assert cfg.api.auth_key == "changeme"


def test_api_tool_invoke_config_custom(tmp_path: Path) -> None:
    cfg = _load_config(
        tmp_path / "config.toml",
        """
[api]
tool_invoke_enabled = true
tool_invoke_expose = "all"
tool_invoke_allowlist = ["get_current_time", "end"]
tool_invoke_denylist = ["python_interpreter"]
tool_invoke_timeout = 60
tool_invoke_callback_timeout = 5
""",
    )
    assert cfg.api.tool_invoke_enabled is True
    assert cfg.api.tool_invoke_expose == "all"
    assert cfg.api.tool_invoke_allowlist == ["get_current_time", "end"]
    assert cfg.api.tool_invoke_denylist == ["python_interpreter"]
    assert cfg.api.tool_invoke_timeout == 60
    assert cfg.api.tool_invoke_callback_timeout == 5


def test_api_tool_invoke_invalid_expose_fallback(tmp_path: Path) -> None:
    cfg = _load_config(
        tmp_path / "config.toml",
        """
[api]
tool_invoke_expose = "invalid_value"
""",
    )
    assert cfg.api.tool_invoke_expose == "tools+toolsets"


def test_api_tool_invoke_invalid_timeout_fallback(tmp_path: Path) -> None:
    cfg = _load_config(
        tmp_path / "config.toml",
        """
[api]
tool_invoke_timeout = -1
tool_invoke_callback_timeout = 0
""",
    )
    assert cfg.api.tool_invoke_timeout == 120
    assert cfg.api.tool_invoke_callback_timeout == 10
