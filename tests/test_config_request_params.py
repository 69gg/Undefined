from __future__ import annotations

from pathlib import Path

from Undefined.config.loader import Config


def _load_config(path: Path, text: str) -> Config:
    path.write_text(text, "utf-8")
    return Config.load(path, strict=False)


def test_model_request_params_load_inherit_and_new_transport_fields(
    tmp_path: Path,
) -> None:
    cfg = _load_config(
        tmp_path / "config.toml",
        """
[onebot]
ws_url = "ws://127.0.0.1:3001"

[models.chat]
api_url = "https://api.openai.com/v1"
api_key = "sk-chat"
model_name = "gpt-chat"
api_mode = "responses"
reasoning_enabled = true
reasoning_effort = "high"
responses_tool_choice_compat = true
responses_force_stateless_replay = true

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
api_mode = "chat_completions"
reasoning_enabled = false
reasoning_effort = "low"

[models.chat.pool.models.request_params]
temperature = 0.6
provider = { name = "pool" }

[models.vision]
api_url = "https://api.openai.com/v1"
api_key = "sk-vision"
model_name = "gpt-vision"
api_mode = "responses"
reasoning_enabled = true
reasoning_effort = "low"
responses_tool_choice_compat = true
responses_force_stateless_replay = true

[models.vision.request_params]
temperature = 0.4
metadata = { source = "vision" }

[models.agent]
api_url = "https://api.openai.com/v1"
api_key = "sk-agent"
model_name = "gpt-agent"
api_mode = "responses"
reasoning_enabled = true
reasoning_effort = "minimal"
responses_tool_choice_compat = true
responses_force_stateless_replay = true

[models.agent.request_params]
temperature = 0.3
metadata = { source = "agent" }
response_format = { type = "json_object" }

[models.historian]
model_name = "gpt-historian"
api_mode = "chat_completions"
reasoning_effort = "xhigh"

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

    assert cfg.chat_model.api_mode == "responses"
    assert cfg.chat_model.reasoning_enabled is True
    assert cfg.chat_model.reasoning_effort == "high"
    assert cfg.chat_model.thinking_tool_call_compat is True
    assert cfg.chat_model.responses_tool_choice_compat is True
    assert cfg.chat_model.responses_force_stateless_replay is True
    assert cfg.chat_model.request_params == {
        "temperature": 0.2,
        "metadata": {"source": "chat"},
    }

    assert cfg.chat_model.pool is not None
    assert cfg.chat_model.pool.models[0].api_mode == "chat_completions"
    assert cfg.chat_model.pool.models[0].reasoning_enabled is False
    assert cfg.chat_model.pool.models[0].reasoning_effort == "low"
    assert cfg.chat_model.pool.models[0].thinking_tool_call_compat is True
    assert cfg.chat_model.pool.models[0].responses_tool_choice_compat is True
    assert cfg.chat_model.pool.models[0].responses_force_stateless_replay is True
    assert cfg.chat_model.pool.models[0].request_params == {
        "temperature": 0.6,
        "metadata": {"source": "chat"},
        "provider": {"name": "pool"},
    }

    assert cfg.vision_model.api_mode == "responses"
    assert cfg.vision_model.reasoning_enabled is True
    assert cfg.vision_model.reasoning_effort == "low"
    assert cfg.vision_model.responses_tool_choice_compat is True
    assert cfg.vision_model.responses_force_stateless_replay is True
    assert cfg.vision_model.request_params == {
        "temperature": 0.4,
        "metadata": {"source": "vision"},
    }

    assert cfg.security_model.api_mode == cfg.chat_model.api_mode
    assert cfg.security_model.reasoning_enabled == cfg.chat_model.reasoning_enabled
    assert cfg.security_model.reasoning_effort == cfg.chat_model.reasoning_effort
    assert cfg.security_model.thinking_tool_call_compat is True
    assert cfg.security_model.responses_tool_choice_compat is True
    assert cfg.security_model.responses_force_stateless_replay is True
    assert cfg.security_model.request_params == cfg.chat_model.request_params

    assert cfg.agent_model.api_mode == "responses"
    assert cfg.agent_model.reasoning_enabled is True
    assert cfg.agent_model.reasoning_effort == "minimal"
    assert cfg.agent_model.thinking_tool_call_compat is True
    assert cfg.agent_model.responses_tool_choice_compat is True
    assert cfg.agent_model.responses_force_stateless_replay is True

    assert cfg.historian_model.api_mode == "chat_completions"
    assert cfg.historian_model.reasoning_enabled is True
    assert cfg.historian_model.reasoning_effort == "xhigh"
    assert cfg.historian_model.thinking_tool_call_compat is True
    assert cfg.historian_model.responses_tool_choice_compat is True
    assert cfg.historian_model.responses_force_stateless_replay is True
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
