from __future__ import annotations

from pathlib import Path

from Undefined.config.loader import Config


def _load_config(path: Path, text: str) -> Config:
    path.write_text(text, "utf-8")
    return Config.load(path, strict=False)


def test_model_request_params_load_and_inherit(tmp_path: Path) -> None:
    cfg = _load_config(
        tmp_path / "config.toml",
        """
[onebot]
ws_url = "ws://127.0.0.1:3001"

[models.chat]
api_url = "https://api.openai.com/v1"
api_key = "sk-chat"
model_name = "gpt-chat"

[models.chat.request_params]
temperature = 0.2
metadata = { source = "chat" }

[models.chat.pool]
enabled = true
strategy = "round_robin"

[[models.chat.pool.models]]
model_name = "gpt-chat-b"
api_url = "https://pool.example/v1"
api_key = "sk-pool"

[models.chat.pool.models.request_params]
temperature = 0.6
provider = { name = "pool" }

[models.agent]
api_url = "https://api.openai.com/v1"
api_key = "sk-agent"
model_name = "gpt-agent"

[models.agent.request_params]
temperature = 0.3
metadata = { source = "agent" }
response_format = { type = "json_object" }

[models.historian]
model_name = "gpt-historian"

[models.historian.request_params]
temperature = 0.1
metadata = { source = "historian" }

[models.embedding]
api_url = "https://api.openai.com/v1"
api_key = "sk-embed"
model_name = "text-embedding-3-small"

[models.embedding.request_params]
encoding_format = "base64"
metadata = { source = "embed" }

[models.rerank]
api_url = "https://api.openai.com/v1"
api_key = "sk-rerank"
model_name = "text-rerank-001"

[models.rerank.request_params]
priority = "high"
""",
    )

    assert cfg.chat_model.request_params == {
        "temperature": 0.2,
        "metadata": {"source": "chat"},
    }
    assert cfg.chat_model.pool is not None
    assert cfg.chat_model.pool.models[0].request_params == {
        "temperature": 0.6,
        "metadata": {"source": "chat"},
        "provider": {"name": "pool"},
    }
    assert cfg.security_model.request_params == cfg.chat_model.request_params
    assert cfg.historian_model.request_params == {
        "temperature": 0.1,
        "metadata": {"source": "historian"},
        "response_format": {"type": "json_object"},
    }
    assert cfg.embedding_model.request_params == {
        "encoding_format": "base64",
        "metadata": {"source": "embed"},
    }
    assert cfg.rerank_model.request_params == {"priority": "high"}
