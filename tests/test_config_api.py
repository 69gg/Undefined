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
