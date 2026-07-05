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


def test_registry_uses_scoped_proxy_env_keys() -> None:
    assert "USE_PROXY" not in ENV_REGISTRY.values()
    assert ENV_REGISTRY[("search", "use_proxy")] == "SEARCH_USE_PROXY"
    assert ENV_REGISTRY[("github", "use_proxy")] == "GITHUB_USE_PROXY"
    assert ENV_REGISTRY[("models", "chat", "use_proxy")] == "CHAT_MODEL_USE_PROXY"
    assert (
        ENV_REGISTRY[("models", "image_gen", "use_proxy")]
        == "IMAGE_GEN_MODEL_USE_PROXY"
    )
