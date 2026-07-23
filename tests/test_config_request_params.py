from __future__ import annotations

from pathlib import Path

from Undefined.config.loader import Config
from Undefined.config.models import (
    AgentModelConfig,
    ChatModelConfig,
    GrokModelConfig,
    SecurityModelConfig,
    VisionModelConfig,
)


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
prompt_cache_enabled = false
stream_enabled = true

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
stream_enabled = true

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
prompt_cache_enabled = false
stream_enabled = true

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
prompt_cache_enabled = false
stream_enabled = true

[models.agent.request_params]
temperature = 0.3
metadata = { source = "agent" }
response_format = { type = "json_object" }

[models.historian]
model_name = "gpt-historian"
api_mode = "chat_completions"
reasoning_effort = "xhigh"
stream_enabled = true

[models.historian.request_params]
temperature = 0.1
metadata = { source = "historian" }

[models.summary]
model_name = "gpt-summary"
api_mode = "chat_completions"
reasoning_effort = "xhigh"
stream_enabled = true

[models.summary.request_params]
temperature = 0.15
metadata = { source = "summary" }

[models.grok]
api_url = "https://grok.example/v1"
api_key = "sk-grok"
model_name = "grok-4-search"
reasoning_enabled = true
reasoning_effort = "low"
stream_enabled = true

[models.grok.request_params]
temperature = 0.5
metadata = { source = "grok" }

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

[models.image_gen]
api_url = "https://image.example.com/v1"
api_key = "sk-image"
model_name = "gpt-image-gen"

[models.image_gen.request_params]
temperature = 0.8

[models.image_edit]
api_url = "https://edit.example.com/v1"
api_key = "sk-image-edit"
model_name = "gpt-image-edit"

[models.image_edit.request_params]
background = "transparent"
""",
    )

    assert cfg.chat_model.api_mode == "openai.responses"
    assert cfg.chat_model.reasoning_enabled is True
    assert cfg.chat_model.reasoning_effort == "high"
    assert cfg.chat_model.thinking_tool_call_compat is True
    assert cfg.chat_model.reasoning_content_replay is True
    assert cfg.chat_model.system_prompt_as_user is False
    assert cfg.chat_model.responses_tool_choice_compat is True
    assert cfg.chat_model.responses_force_stateless_replay is True
    assert cfg.chat_model.prompt_cache_enabled is False
    assert cfg.chat_model.stream_enabled is True
    assert cfg.chat_model.request_params == {
        "temperature": 0.2,
        "metadata": {"source": "chat"},
    }

    assert cfg.chat_model.pool is not None
    assert cfg.chat_model.pool.models[0].api_mode == "openai.chat_completions"
    assert cfg.chat_model.pool.models[0].reasoning_enabled is False
    assert cfg.chat_model.pool.models[0].reasoning_effort == "low"
    assert cfg.chat_model.pool.models[0].thinking_tool_call_compat is True
    assert cfg.chat_model.pool.models[0].reasoning_content_replay is True
    assert cfg.chat_model.pool.models[0].system_prompt_as_user is False
    assert cfg.chat_model.pool.models[0].responses_tool_choice_compat is True
    assert cfg.chat_model.pool.models[0].responses_force_stateless_replay is True
    assert cfg.chat_model.pool.models[0].prompt_cache_enabled is False
    assert cfg.chat_model.pool.models[0].stream_enabled is True
    assert cfg.chat_model.pool.models[0].request_params == {
        "temperature": 0.6,
        "metadata": {"source": "chat"},
        "provider": {"name": "pool"},
    }

    assert cfg.vision_model.api_mode == "openai.responses"
    assert cfg.vision_model.reasoning_enabled is True
    assert cfg.vision_model.reasoning_effort == "low"
    assert cfg.vision_model.responses_tool_choice_compat is True
    assert cfg.vision_model.responses_force_stateless_replay is True
    assert cfg.vision_model.prompt_cache_enabled is False
    assert cfg.vision_model.stream_enabled is True
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
    assert cfg.security_model.prompt_cache_enabled is False
    assert cfg.security_model.stream_enabled is True
    assert cfg.security_model.request_params == cfg.chat_model.request_params

    assert cfg.naga_model.api_mode == cfg.security_model.api_mode
    assert cfg.naga_model.reasoning_enabled == cfg.security_model.reasoning_enabled
    assert cfg.naga_model.reasoning_effort == cfg.security_model.reasoning_effort
    assert cfg.naga_model.stream_enabled is True
    assert cfg.naga_model.request_params == cfg.security_model.request_params

    assert cfg.agent_model.api_mode == "openai.responses"
    assert cfg.agent_model.reasoning_enabled is True
    assert cfg.agent_model.reasoning_effort == "minimal"
    assert cfg.agent_model.thinking_tool_call_compat is True
    assert cfg.agent_model.responses_tool_choice_compat is True
    assert cfg.agent_model.responses_force_stateless_replay is True
    assert cfg.agent_model.prompt_cache_enabled is False
    assert cfg.agent_model.stream_enabled is True

    assert cfg.historian_model.api_mode == "openai.chat_completions"
    assert cfg.historian_model.reasoning_enabled is True
    assert cfg.historian_model.reasoning_effort == "xhigh"
    assert cfg.historian_model.thinking_tool_call_compat is True
    assert cfg.historian_model.responses_tool_choice_compat is True
    assert cfg.historian_model.responses_force_stateless_replay is True
    assert cfg.historian_model.prompt_cache_enabled is False
    assert cfg.historian_model.stream_enabled is True
    assert cfg.historian_model.request_params == {
        "temperature": 0.1,
        "metadata": {"source": "historian"},
        "response_format": {"type": "json_object"},
    }
    assert cfg.summary_model.api_mode == "openai.chat_completions"
    assert cfg.summary_model.reasoning_enabled is True
    assert cfg.summary_model.reasoning_effort == "xhigh"
    assert cfg.summary_model.thinking_tool_call_compat is True
    assert cfg.summary_model.responses_tool_choice_compat is True
    assert cfg.summary_model.responses_force_stateless_replay is True
    assert cfg.summary_model.prompt_cache_enabled is False
    assert cfg.summary_model.stream_enabled is True
    assert cfg.summary_model.request_params == {
        "temperature": 0.15,
        "metadata": {"source": "summary"},
        "response_format": {"type": "json_object"},
    }
    assert cfg.grok_model.reasoning_enabled is True
    assert cfg.grok_model.reasoning_effort == "low"
    assert cfg.grok_model.prompt_cache_enabled is True
    assert cfg.grok_model.stream_enabled is True
    assert cfg.grok_model.request_params == {
        "temperature": 0.5,
        "metadata": {"source": "grok"},
    }

    assert cfg.embedding_model.request_params == {
        "encoding_format": "base64",
        "metadata": {"source": "embed"},
    }
    assert cfg.rerank_model.request_params == {"priority": "high"}
    assert cfg.models_image_gen.api_url == "https://image.example.com/v1"
    assert cfg.models_image_gen.api_key == "sk-image"
    assert cfg.models_image_gen.model_name == "gpt-image-gen"
    assert cfg.models_image_gen.request_params == {"temperature": 0.8}
    assert cfg.models_image_edit.api_url == "https://edit.example.com/v1"
    assert cfg.models_image_edit.api_key == "sk-image-edit"
    assert cfg.models_image_edit.model_name == "gpt-image-edit"
    assert cfg.models_image_edit.request_params == {"background": "transparent"}


def test_naga_model_request_params_override_security_defaults(tmp_path: Path) -> None:
    cfg = _load_config(
        tmp_path / "config.toml",
        """
[onebot]
ws_url = "ws://127.0.0.1:3001"

[models.chat]
api_url = "https://api.openai.com/v1"
api_key = "sk-chat"
model_name = "gpt-chat"

[models.security]
api_url = "https://api.openai.com/v1"
api_key = "sk-security"
model_name = "gpt-security"
reasoning_enabled = true
reasoning_effort = "high"

[models.security.request_params]
temperature = 0.1

[models.naga]
api_url = "https://api.openai.com/v1"
api_key = "sk-naga"
model_name = "gpt-naga"
api_mode = "responses"
reasoning_enabled = false
reasoning_effort = "low"

[models.naga.request_params]
temperature = 0.6
metadata = { source = "naga" }
""",
    )

    assert cfg.naga_model.model_name == "gpt-naga"
    assert cfg.naga_model.api_mode == "openai.responses"
    assert cfg.naga_model.reasoning_enabled is False
    assert cfg.naga_model.reasoning_effort == "low"
    assert cfg.naga_model.request_params == {
        "temperature": 0.6,
        "metadata": {"source": "naga"},
    }


def test_grok_search_switch_defaults_false_and_can_enable(tmp_path: Path) -> None:
    cfg = _load_config(
        tmp_path / "config.toml",
        """
[search]
grok_search_enabled = true
""",
    )

    assert cfg.grok_search_enabled is True
    assert cfg.grok_model.model_name == ""


def test_all_generation_models_and_pools_support_transport_settings(
    tmp_path: Path,
) -> None:
    cfg = _load_config(
        tmp_path / "config.toml",
        """
[onebot]
ws_url = "ws://127.0.0.1:3001"

[models.chat]
api_url = "https://provider.example"
api_key = "chat-key"
model_name = "chat-model"
max_tokens = 0
api_mode = "anthropic.messages"
thinking_param_enabled = false
reasoning_content_replay = false
reasoning_enabled = true
reasoning_effort = "Vendor-Custom"

[models.chat.pool]
enabled = true
strategy = "round_robin"

[[models.chat.pool.models]]
api_url = "https://pool.example/v1"
api_key = "pool-key"
model_name = "chat-pool"
max_tokens = -2
api_mode = "openai.responses"
thinking_param_enabled = true
reasoning_content_replay = true
reasoning_enabled = true
reasoning_effort = "adaptive"

[models.vision]
api_url = "https://provider.example"
api_key = "vision-key"
model_name = "vision-model"
max_tokens = -1
api_mode = "anthropic.messages"
thinking_param_enabled = false
reasoning_content_replay = false
reasoning_enabled = true
reasoning_effort = "Vendor-Custom"

[models.security]
api_url = "https://provider.example"
api_key = "security-key"
model_name = "security-model"
max_tokens = 0
api_mode = "anthropic.messages"
thinking_param_enabled = false
reasoning_content_replay = false
reasoning_enabled = true
reasoning_effort = "Vendor-Custom"

[models.naga]
api_url = "https://provider.example"
api_key = "naga-key"
model_name = "naga-model"
max_tokens = -1
api_mode = "anthropic.messages"
thinking_param_enabled = false
reasoning_content_replay = false
reasoning_enabled = true
reasoning_effort = "Vendor-Custom"

[models.agent]
api_url = "https://provider.example"
api_key = "agent-key"
model_name = "agent-model"
max_tokens = 0
api_mode = "anthropic.messages"
thinking_param_enabled = false
reasoning_content_replay = false
reasoning_enabled = true
reasoning_effort = "Vendor-Custom"
thinking_include_budget = false
thinking_tool_call_compat = false

[models.agent.pool]
enabled = true
strategy = "round_robin"

[[models.agent.pool.models]]
api_url = "https://pool.example/v1"
api_key = "pool-key"
model_name = "agent-pool"
max_tokens = -2
api_mode = "openai.responses"
thinking_param_enabled = true
reasoning_content_replay = true
reasoning_enabled = true
reasoning_effort = "adaptive"

[models.historian]
model_name = "historian-model"
max_tokens = -1
api_mode = "anthropic.messages"
thinking_param_enabled = false
reasoning_content_replay = false
reasoning_enabled = true
reasoning_effort = "Vendor-Custom"

[models.summary]
model_name = "summary-model"
max_tokens = 0
api_mode = "anthropic.messages"
thinking_param_enabled = false
reasoning_content_replay = false
reasoning_enabled = true
reasoning_effort = "Vendor-Custom"

[models.grok]
api_url = "https://provider.example"
api_key = "grok-key"
model_name = "grok-model"
max_tokens = -1
api_mode = "anthropic.messages"
thinking_param_enabled = false
reasoning_content_replay = false
reasoning_enabled = true
reasoning_effort = "Vendor-Custom"
""",
    )

    generation_models: list[
        ChatModelConfig
        | VisionModelConfig
        | SecurityModelConfig
        | AgentModelConfig
        | GrokModelConfig
    ] = [
        cfg.chat_model,
        cfg.vision_model,
        cfg.security_model,
        cfg.naga_model,
        cfg.agent_model,
        cfg.historian_model,
        cfg.summary_model,
        cfg.grok_model,
    ]
    for model in generation_models:
        assert model.api_mode == "anthropic.messages"
        assert model.reasoning_content_replay is False
        assert model.thinking_param_enabled is False
        assert model.reasoning_enabled is True
        assert model.reasoning_effort == "Vendor-Custom"
        assert model.responses_tool_choice_compat is False

    assert [model.max_tokens for model in generation_models] == [
        0,
        -1,
        0,
        -1,
        0,
        -1,
        0,
        -1,
    ]

    assert cfg.chat_model.pool is not None
    assert cfg.agent_model.pool is not None
    for entry in [
        cfg.chat_model.pool.models[0],
        cfg.agent_model.pool.models[0],
    ]:
        assert entry.api_mode == "openai.responses"
        assert entry.reasoning_content_replay is True
        assert entry.thinking_param_enabled is True
        assert entry.reasoning_enabled is True
        assert entry.reasoning_effort == "adaptive"
        assert entry.max_tokens == -2

    assert cfg.historian_model.thinking_include_budget is False
    assert cfg.historian_model.thinking_tool_call_compat is False
    assert cfg.summary_model.thinking_include_budget is False
    assert cfg.summary_model.thinking_tool_call_compat is False


def test_thinking_param_enabled_defaults_and_fallbacks(tmp_path: Path) -> None:
    cfg = _load_config(
        tmp_path / "config.toml",
        """
[models.chat]
api_url = "https://provider.example/v1"
api_key = "chat-key"
model_name = "chat-model"
thinking_param_enabled = false

[models.agent]
api_url = "https://provider.example/v1"
api_key = "agent-key"
model_name = "agent-model"
thinking_param_enabled = false
""",
    )

    assert cfg.chat_model.thinking_param_enabled is False
    assert cfg.security_model.thinking_param_enabled is False
    assert cfg.naga_model.thinking_param_enabled is False
    assert cfg.agent_model.thinking_param_enabled is False
    assert cfg.historian_model.thinking_param_enabled is False
    assert cfg.summary_model.thinking_param_enabled is False
    assert cfg.vision_model.thinking_param_enabled is True
    assert cfg.grok_model.thinking_param_enabled is True
