"""TOML path to environment variable mapping for configuration."""

from __future__ import annotations


from typing import Final

_GENERATION_MODEL_ENV_PREFIXES: Final[dict[str, str]] = {
    "agent": "AGENT",
    "chat": "CHAT",
    "grok": "GROK",
    "naga": "NAGA",
    "security": "SECURITY",
    "vision": "VISION",
}
_GENERATION_MODEL_ENV_FIELDS: Final[dict[str, str]] = {
    "api_key": "API_KEY",
    "api_mode": "API_MODE",
    "api_url": "API_URL",
    "context_window_tokens": "CONTEXT_WINDOW_TOKENS",
    "max_tokens": "MAX_TOKENS",
    "model_name": "NAME",
    "prompt_cache_enabled": "PROMPT_CACHE_ENABLED",
    "queue_interval_seconds": "QUEUE_INTERVAL",
    "reasoning_content_replay": "REASONING_CONTENT_REPLAY",
    "reasoning_effort": "REASONING_EFFORT",
    "reasoning_enabled": "REASONING_ENABLED",
    "responses_force_stateless_replay": "RESPONSES_FORCE_STATELESS_REPLAY",
    "responses_tool_choice_compat": "RESPONSES_TOOL_CHOICE_COMPAT",
    "stream_enabled": "STREAM_ENABLED",
    "system_prompt_as_user": "SYSTEM_PROMPT_AS_USER",
    "thinking_budget_tokens": "THINKING_BUDGET_TOKENS",
    "thinking_enabled": "THINKING_ENABLED",
    "thinking_include_budget": "THINKING_INCLUDE_BUDGET",
    "thinking_tool_call_compat": "THINKING_TOOL_CALL_COMPAT",
    "use_proxy": "USE_PROXY",
}
_GENERATION_MODEL_ENV_REGISTRY: Final[dict[tuple[str, ...], str]] = {
    ("models", model_name, field_name): f"{prefix}_MODEL_{suffix}"
    for model_name, prefix in _GENERATION_MODEL_ENV_PREFIXES.items()
    for field_name, suffix in _GENERATION_MODEL_ENV_FIELDS.items()
}

# TOML 路径 → 环境变量名；供 _get_value 在 TOML 缺省时回退，以及文档/工具生成
ENV_REGISTRY: Final[dict[tuple[str, ...], str]] = {
    **_GENERATION_MODEL_ENV_REGISTRY,
    ("access", "allowed_group_ids"): "ALLOWED_GROUP_IDS",
    ("access", "allowed_private_ids"): "ALLOWED_PRIVATE_IDS",
    ("access", "blocked_group_ids"): "BLOCKED_GROUP_IDS",
    ("access", "blocked_private_ids"): "BLOCKED_PRIVATE_IDS",
    ("access", "mode"): "ACCESS_MODE",
    (
        "api",
        "tool_invoke_callback_use_proxy",
    ): "API_TOOL_INVOKE_CALLBACK_USE_PROXY",
    ("api_endpoints", "jkyai_base_url"): "JKYAI_BASE_URL",
    ("api_endpoints", "xxapi_base_url"): "XXAPI_BASE_URL",
    ("core", "admin_qq"): "ADMIN_QQ",
    ("core", "bot_qq"): "BOT_QQ",
    ("core", "forward_proxy_qq"): "FORWARD_PROXY_QQ",
    ("core", "superadmin_qq"): "SUPERADMIN_QQ",
    ("features", "pool_enabled"): "MODEL_POOL_ENABLED",
    ("attachments", "use_proxy"): "ATTACHMENTS_USE_PROXY",
    ("arxiv", "use_proxy"): "ARXIV_USE_PROXY",
    ("bilibili", "use_proxy"): "BILIBILI_USE_PROXY",
    ("github", "use_proxy"): "GITHUB_USE_PROXY",
    ("history", "max_records"): "HISTORY_MAX_RECORDS",
    ("image_gen", "use_proxy"): "IMAGE_GEN_USE_PROXY",
    ("image_gen", "provider"): "IMAGE_GEN_PROVIDER",
    ("logging", "backup_count"): "LOG_BACKUP_COUNT",
    ("logging", "file_path"): "LOG_FILE_PATH",
    ("logging", "level"): "LOG_LEVEL",
    ("logging", "log_thinking"): "LOG_THINKING",
    ("logging", "max_size_mb"): "LOG_MAX_SIZE_MB",
    ("logging", "tty_enabled"): "LOG_TTY_ENABLED",
    ("mcp", "config_path"): "MCP_CONFIG_PATH",
    (
        "models",
        "embedding",
        "context_window_tokens",
    ): "EMBEDDING_MODEL_CONTEXT_WINDOW_TOKENS",
    ("models", "embedding", "api_key"): "EMBEDDING_MODEL_API_KEY",
    ("models", "embedding", "api_url"): "EMBEDDING_MODEL_API_URL",
    ("models", "embedding", "model_name"): "EMBEDDING_MODEL_NAME",
    ("models", "embedding", "use_proxy"): "EMBEDDING_MODEL_USE_PROXY",
    ("models", "historian", "use_proxy"): "HISTORIAN_MODEL_USE_PROXY",
    (
        "models",
        "historian",
        "reasoning_content_replay",
    ): "HISTORIAN_MODEL_REASONING_CONTENT_REPLAY",
    (
        "models",
        "historian",
        "system_prompt_as_user",
    ): "HISTORIAN_MODEL_SYSTEM_PROMPT_AS_USER",
    ("models", "image_edit", "use_proxy"): "IMAGE_EDIT_MODEL_USE_PROXY",
    ("models", "image_gen", "use_proxy"): "IMAGE_GEN_MODEL_USE_PROXY",
    ("models", "rerank", "api_key"): "RERANK_MODEL_API_KEY",
    ("models", "rerank", "api_url"): "RERANK_MODEL_API_URL",
    ("models", "rerank", "context_window_tokens"): "RERANK_MODEL_CONTEXT_WINDOW_TOKENS",
    ("models", "rerank", "model_name"): "RERANK_MODEL_NAME",
    ("models", "rerank", "use_proxy"): "RERANK_MODEL_USE_PROXY",
    ("models", "summary", "use_proxy"): "SUMMARY_MODEL_USE_PROXY",
    (
        "models",
        "summary",
        "reasoning_content_replay",
    ): "SUMMARY_MODEL_REASONING_CONTENT_REPLAY",
    (
        "models",
        "summary",
        "system_prompt_as_user",
    ): "SUMMARY_MODEL_SYSTEM_PROMPT_AS_USER",
    ("messages", "use_proxy"): "MESSAGES_USE_PROXY",
    ("naga", "use_proxy"): "NAGA_USE_PROXY",
    ("onebot", "token"): "ONEBOT_TOKEN",
    ("onebot", "ws_url"): "ONEBOT_WS_URL",
    ("render", "browser_executable_path"): "RENDER_BROWSER_EXECUTABLE_PATH",
    ("render", "long_image_default_padding"): "RENDER_LONG_IMAGE_DEFAULT_PADDING",
    ("render", "long_image_default_width"): "RENDER_LONG_IMAGE_DEFAULT_WIDTH",
    ("render", "use_proxy"): "RENDER_USE_PROXY",
    ("search", "use_proxy"): "SEARCH_USE_PROXY",
    ("search", "firecrawl_search_enabled"): "FIRECRAWL_SEARCH_ENABLED",
    ("search", "firecrawl", "api_key"): "FIRECRAWL_API_KEY",
    ("search", "firecrawl", "base_url"): "FIRECRAWL_BASE_URL",
    ("search", "priority"): "SEARCH_PRIORITY",
    ("search", "searxng_url"): "SEARXNG_URL",
    ("skills", "hot_reload"): "SKILLS_HOT_RELOAD",
    ("skills", "intro_hash_path"): "AGENT_INTRO_HASH_PATH",
    ("skills", "prefetch_tools_hide"): "PREFETCH_TOOLS_HIDE",
    ("skills", "tool_search_always_loaded"): "TOOL_SEARCH_ALWAYS_LOADED",
    ("skills", "tool_search_enabled"): "TOOL_SEARCH_ENABLED",
    ("skills", "tool_search_max_results"): "TOOL_SEARCH_MAX_RESULTS",
    ("token_usage", "max_archives"): "TOKEN_USAGE_MAX_ARCHIVES",
    ("token_usage", "max_size_mb"): "TOKEN_USAGE_MAX_SIZE_MB",
    ("token_usage", "max_total_mb"): "TOKEN_USAGE_MAX_TOTAL_MB",
    ("tools", "description_max_len"): "TOOLS_DESCRIPTION_MAX_LEN",
    ("tools", "dot_delimiter"): "TOOLS_DOT_DELIMITER",
    ("tools", "sanitize_verbose"): "TOOLS_SANITIZE_VERBOSE",
    ("weather", "api_key"): "WEATHER_API_KEY",
    ("xxapi", "api_token"): "XXAPI_API_TOKEN",
}

# 历史/别名环境变量：不经过 _get_value 统一路径，单独在 domain_parsers 等处读取
ENV_ALTERNATES: Final[dict[str, tuple[str, ...]]] = {
    "EASTER_EGG_AGENT_CALL_MESSAGE_MODE": ("easter_egg", "agent_call_message_enabled"),
    "EASTER_EGG_CALL_MESSAGE_MODE": ("easter_egg", "agent_call_message_enabled"),
    "HTTP_PROXY": ("proxy", "http_proxy"),
    "HTTPS_PROXY": ("proxy", "https_proxy"),
}


def env_key_for_path(path: tuple[str, ...]) -> str | None:
    """Return primary env var for a TOML path, if registered."""
    return ENV_REGISTRY.get(path)


def all_env_mappings() -> dict[tuple[str, ...], str]:
    """Return a copy of the primary env registry."""
    return dict(ENV_REGISTRY)
