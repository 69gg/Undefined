from __future__ import annotations

from pathlib import Path

from Undefined.config.loader import Config
from Undefined.services.queue_manager import QueueManager
from Undefined.utils.queue_intervals import build_model_queue_intervals


def _load_config(path: Path, text: str) -> Config:
    path.write_text(text, "utf-8")
    return Config.load(path, strict=False)


def test_zero_queue_intervals_are_preserved_for_immediate_dispatch(
    tmp_path: Path,
) -> None:
    cfg = _load_config(
        tmp_path / "config.toml",
        """
[skills]
intro_autogen_queue_interval = 0

[models.chat]
api_url = "https://api.openai.com/v1"
api_key = "sk-chat"
model_name = "chat-model"
queue_interval_seconds = 0

[models.chat.pool]
enabled = true
strategy = "round_robin"

[[models.chat.pool.models]]
model_name = "chat-pool-model"
queue_interval_seconds = 0

[models.vision]
api_url = "https://api.openai.com/v1"
api_key = "sk-vision"
model_name = "vision-model"
queue_interval_seconds = 0

[models.security]
api_url = "https://api.openai.com/v1"
api_key = "sk-security"
model_name = "security-model"
queue_interval_seconds = 0

[models.naga]
api_url = "https://api.openai.com/v1"
api_key = "sk-naga"
model_name = "naga-model"
queue_interval_seconds = 0

[models.agent]
api_url = "https://api.openai.com/v1"
api_key = "sk-agent"
model_name = "agent-model"
queue_interval_seconds = 0

[models.historian]
model_name = "historian-model"
queue_interval_seconds = 0

[models.summary]
model_name = "summary-model"
queue_interval_seconds = 0

[models.grok]
api_url = "https://grok.example/v1"
api_key = "sk-grok"
model_name = "grok-model"
queue_interval_seconds = 0

[models.embedding]
api_url = "https://api.openai.com/v1"
api_key = "sk-embed"
model_name = "text-embedding-3-small"
queue_interval_seconds = 0

[models.rerank]
api_url = "https://api.openai.com/v1"
api_key = "sk-rerank"
model_name = "text-rerank-001"
queue_interval_seconds = 0
""",
    )

    assert cfg.agent_intro_autogen_queue_interval == 0.0
    assert cfg.chat_model.queue_interval_seconds == 0.0
    assert cfg.chat_model.pool is not None
    assert cfg.chat_model.pool.models[0].queue_interval_seconds == 0.0
    assert cfg.vision_model.queue_interval_seconds == 0.0
    assert cfg.security_model.queue_interval_seconds == 0.0
    assert cfg.naga_model.queue_interval_seconds == 0.0
    assert cfg.agent_model.queue_interval_seconds == 0.0
    assert cfg.historian_model.queue_interval_seconds == 0.0
    assert cfg.summary_model.queue_interval_seconds == 0.0
    assert cfg.grok_model.queue_interval_seconds == 0.0
    assert cfg.embedding_model.queue_interval_seconds == 0.0
    assert cfg.rerank_model.queue_interval_seconds == 0.0

    queue_manager = QueueManager(model_intervals=build_model_queue_intervals(cfg))
    assert queue_manager.get_interval("chat-model") == 0.0
    assert queue_manager.get_interval("chat-pool-model") == 0.0
    assert queue_manager.get_interval("agent-model") == 0.0
    assert queue_manager.get_interval("summary-model") == 0.0
    assert queue_manager.get_interval("grok-model") == 0.0
    assert queue_manager.get_interval("naga-model") == 0.0


def test_negative_queue_intervals_still_fall_back_to_defaults(tmp_path: Path) -> None:
    cfg = _load_config(
        tmp_path / "config.toml",
        """
[skills]
intro_autogen_queue_interval = -1

[models.chat]
api_url = "https://api.openai.com/v1"
api_key = "sk-chat"
model_name = "chat-model"
queue_interval_seconds = 0

[models.chat.pool]
enabled = true
strategy = "round_robin"

[[models.chat.pool.models]]
model_name = "chat-pool-model"
queue_interval_seconds = -1

[models.vision]
api_url = "https://api.openai.com/v1"
api_key = "sk-vision"
model_name = "vision-model"
queue_interval_seconds = -1

[models.agent]
api_url = "https://api.openai.com/v1"
api_key = "sk-agent"
model_name = "agent-model"
queue_interval_seconds = 0.5

[models.historian]
model_name = "historian-model"
queue_interval_seconds = -1

[models.summary]
model_name = "summary-model"
queue_interval_seconds = -1

[models.grok]
api_url = "https://grok.example/v1"
api_key = "sk-grok"
model_name = "grok-model"
queue_interval_seconds = -1

[models.embedding]
api_url = "https://api.openai.com/v1"
api_key = "sk-embed"
model_name = "text-embedding-3-small"
queue_interval_seconds = -1

[models.rerank]
api_url = "https://api.openai.com/v1"
api_key = "sk-rerank"
model_name = "text-rerank-001"
queue_interval_seconds = -1
""",
    )

    assert cfg.agent_intro_autogen_queue_interval == 1.0
    assert cfg.chat_model.queue_interval_seconds == 0.0
    assert cfg.chat_model.pool is not None
    assert cfg.chat_model.pool.models[0].queue_interval_seconds == 0.0
    assert cfg.vision_model.queue_interval_seconds == 1.0
    assert cfg.agent_model.queue_interval_seconds == 0.5
    assert cfg.historian_model.queue_interval_seconds == 0.5
    assert cfg.summary_model.queue_interval_seconds == 0.5
    assert cfg.grok_model.queue_interval_seconds == 1.0
    assert cfg.embedding_model.queue_interval_seconds == 0.0
    assert cfg.rerank_model.queue_interval_seconds == 0.0


def test_embedding_and_rerank_default_to_immediate_dispatch_when_unset(
    tmp_path: Path,
) -> None:
    cfg = _load_config(
        tmp_path / "config.toml",
        """
[models.embedding]
api_url = "https://api.openai.com/v1"
api_key = "sk-embed"
model_name = "text-embedding-3-small"

[models.rerank]
api_url = "https://api.openai.com/v1"
api_key = "sk-rerank"
model_name = "text-rerank-001"
""",
    )

    assert cfg.embedding_model.queue_interval_seconds == 0.0
    assert cfg.rerank_model.queue_interval_seconds == 0.0


def test_queue_manager_allows_zero_default_interval() -> None:
    zero_default = QueueManager(ai_request_interval=0.0)
    assert zero_default.get_interval("unknown-model") == 0.0

    queue_manager = QueueManager(
        ai_request_interval=0.25,
        model_intervals={
            "fallback-model": -1.0,
            "immediate-model": 0.0,
        },
    )
    assert queue_manager.get_interval("fallback-model") == 0.25
    assert queue_manager.get_interval("immediate-model") == 0.0
