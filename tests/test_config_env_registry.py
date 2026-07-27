from __future__ import annotations

from Undefined.config.env_registry import (
    ENV_ALTERNATES,
    ENV_REGISTRY,
    all_env_mappings,
    env_key_for_path,
)


def test_registry_contains_core_paths() -> None:
    assert ENV_REGISTRY[("core", "bot_qq")] == "BOT_QQ"
    assert ENV_REGISTRY[("onebot", "ws_url")] == "ONEBOT_WS_URL"
    assert ENV_REGISTRY[("models", "chat", "api_url")] == "CHAT_MODEL_API_URL"


def test_env_key_for_path_lookup() -> None:
    assert env_key_for_path(("models", "agent", "model_name")) == "AGENT_MODEL_NAME"
    assert env_key_for_path(("nonexistent",)) is None


def test_all_env_mappings_is_copy() -> None:
    snapshot = all_env_mappings()
    snapshot[("fake",)] = "FAKE"
    assert ("fake",) not in ENV_REGISTRY


def test_alternate_env_keys_documented() -> None:
    assert "HTTP_PROXY" in ENV_ALTERNATES
    assert "EASTER_EGG_CALL_MESSAGE_MODE" in ENV_ALTERNATES


def test_registry_has_model_context_window_entries() -> None:
    assert ("models", "chat", "context_window_tokens") in ENV_REGISTRY


def test_registry_has_search_firecrawl_entries() -> None:
    assert ENV_REGISTRY[("search", "priority")] == "SEARCH_PRIORITY"
    assert (
        ENV_REGISTRY[("search", "firecrawl_search_enabled")]
        == "FIRECRAWL_SEARCH_ENABLED"
    )
    assert ENV_REGISTRY[("search", "firecrawl", "api_key")] == "FIRECRAWL_API_KEY"
    assert ENV_REGISTRY[("search", "firecrawl", "base_url")] == "FIRECRAWL_BASE_URL"


def test_registry_has_tool_search_entries() -> None:
    assert ENV_REGISTRY[("skills", "tool_search_enabled")] == "TOOL_SEARCH_ENABLED"
    assert (
        ENV_REGISTRY[("skills", "tool_search_always_loaded")]
        == "TOOL_SEARCH_ALWAYS_LOADED"
    )
    assert (
        ENV_REGISTRY[("skills", "tool_search_max_results")] == "TOOL_SEARCH_MAX_RESULTS"
    )


def test_registry_has_long_image_render_entries() -> None:
    assert (
        ENV_REGISTRY[("render", "browser_executable_path")]
        == "RENDER_BROWSER_EXECUTABLE_PATH"
    )
    assert (
        ENV_REGISTRY[("render", "long_image_default_width")]
        == "RENDER_LONG_IMAGE_DEFAULT_WIDTH"
    )
    assert (
        ENV_REGISTRY[("render", "long_image_default_padding")]
        == "RENDER_LONG_IMAGE_DEFAULT_PADDING"
    )


def test_registry_uses_scoped_proxy_env_keys() -> None:
    assert "USE_PROXY" not in ENV_REGISTRY.values()
    assert ENV_REGISTRY[("search", "use_proxy")] == "SEARCH_USE_PROXY"
    assert ENV_REGISTRY[("github", "use_proxy")] == "GITHUB_USE_PROXY"
    assert ENV_REGISTRY[("models", "chat", "use_proxy")] == "CHAT_MODEL_USE_PROXY"
    assert (
        ENV_REGISTRY[("models", "image_gen", "use_proxy")]
        == "IMAGE_GEN_MODEL_USE_PROXY"
    )


def test_generation_transport_env_keys_cover_every_primary_model() -> None:
    for model_name, prefix in {
        "chat": "CHAT",
        "vision": "VISION",
        "security": "SECURITY",
        "naga": "NAGA",
        "agent": "AGENT",
        "grok": "GROK",
    }.items():
        assert ENV_REGISTRY[("models", model_name, "api_mode")] == (
            f"{prefix}_MODEL_API_MODE"
        )
        assert ENV_REGISTRY[("models", model_name, "reasoning_content_replay")] == (
            f"{prefix}_MODEL_REASONING_CONTENT_REPLAY"
        )
        assert ENV_REGISTRY[("models", model_name, "reasoning_effort")] == (
            f"{prefix}_MODEL_REASONING_EFFORT"
        )
        assert ENV_REGISTRY[("models", model_name, "thinking_enabled")] == (
            f"{prefix}_MODEL_THINKING_ENABLED"
        )
        assert ENV_REGISTRY[("models", model_name, "thinking_param_enabled")] == (
            f"{prefix}_MODEL_THINKING_PARAM_ENABLED"
        )

    assert ENV_REGISTRY[("models", "historian", "reasoning_content_replay")] == (
        "HISTORIAN_MODEL_REASONING_CONTENT_REPLAY"
    )
    assert ENV_REGISTRY[("models", "summary", "reasoning_content_replay")] == (
        "SUMMARY_MODEL_REASONING_CONTENT_REPLAY"
    )
    assert ENV_REGISTRY[("models", "historian", "thinking_param_enabled")] == (
        "HISTORIAN_MODEL_THINKING_PARAM_ENABLED"
    )
    assert ENV_REGISTRY[("models", "summary", "thinking_param_enabled")] == (
        "SUMMARY_MODEL_THINKING_PARAM_ENABLED"
    )
