from __future__ import annotations

from pathlib import Path

from Undefined.config.loader import Config


_MINIMAL = """
[onebot]
ws_url = "ws://127.0.0.1:3001"
[models.chat]
api_url = "https://api.example/v1"
api_key = "sk-test"
model_name = "gpt-test"
"""


def _load(tmp_path: Path, extra: str = "") -> Config:
    config_path = tmp_path / "config.toml"
    config_path.write_text(_MINIMAL + extra, "utf-8")
    return Config.load(config_path, strict=False)


def test_missing_tool_call_retries_defaults_to_three(tmp_path: Path) -> None:
    cfg = _load(tmp_path)
    assert cfg.missing_tool_call_retries == 3


def test_missing_tool_call_retries_clamps_negative(tmp_path: Path) -> None:
    cfg = _load(tmp_path, "\n[core]\nmissing_tool_call_retries = -1\n")
    assert cfg.missing_tool_call_retries == 0


def test_missing_tool_call_retries_loads_explicit_value(tmp_path: Path) -> None:
    cfg = _load(tmp_path, "\n[core]\nmissing_tool_call_retries = 5\n")
    assert cfg.missing_tool_call_retries == 5
