from __future__ import annotations

from pathlib import Path

from Undefined.config.loader import Config


def _load_config(path: Path, text: str) -> Config:
    path.write_text(text, "utf-8")
    return Config.load(path, strict=False)


def test_chat_model_context_window_tokens_from_config(tmp_path: Path) -> None:
    cfg = _load_config(
        tmp_path / "config.toml",
        """
[onebot]
ws_url = "ws://127.0.0.1:3001"

[models.chat]
api_url = "https://api.example.com/v1"
api_key = "key"
model_name = "gpt-test"
max_tokens = 4096
context_window_tokens = 16384
""",
    )
    assert cfg.chat_model.context_window_tokens == 16384


def test_summary_model_inherits_agent_context_window_when_unset(
    tmp_path: Path,
) -> None:
    cfg = _load_config(
        tmp_path / "config.toml",
        """
[onebot]
ws_url = "ws://127.0.0.1:3001"

[models.agent]
api_url = "https://api.example.com/v1"
api_key = "key"
model_name = "agent-model"
max_tokens = 4096
context_window_tokens = 12288

[models.summary]
model_name = "summary-model"
""",
    )
    assert cfg.agent_model.context_window_tokens == 12288
    assert cfg.summary_model.context_window_tokens == 12288
