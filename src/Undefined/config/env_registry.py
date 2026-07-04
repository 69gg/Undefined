"""TOML path to environment variable mapping for configuration."""

from __future__ import annotations


from typing import Final

# TOML 路径 → 环境变量名；供 _get_value 在 TOML 缺省时回退，以及文档/工具生成
ENV_REGISTRY: Final[dict[tuple[str, ...], str]] = {
    ("access", "allowed_group_ids"): "ALLOWED_GROUP_IDS",
    ("access", "allowed_private_ids"): "ALLOWED_PRIVATE_IDS",
    ("access", "blocked_group_ids"): "BLOCKED_GROUP_IDS",
    ("access", "blocked_private_ids"): "BLOCKED_PRIVATE_IDS",
    ("access", "mode"): "ACCESS_MODE",
    ("api_endpoints", "jkyai_base_url"): "JKYAI_BASE_URL",
    ("api_endpoints", "xxapi_base_url"): "XXAPI_BASE_URL",
    ("core", "admin_qq"): "ADMIN_QQ",
    ("core", "bot_qq"): "BOT_QQ",
    ("core", "forward_proxy_qq"): "FORWARD_PROXY_QQ",
    ("core", "superadmin_qq"): "SUPERADMIN_QQ",
    ("features", "pool_enabled"): "MODEL_POOL_ENABLED",
    ("history", "max_records"): "HISTORY_MAX_RECORDS",
    ("image_gen", "provider"): "IMAGE_GEN_PROVIDER",
    ("logging", "backup_count"): "LOG_BACKUP_COUNT",
    ("logging", "file_path"): "LOG_FILE_PATH",
    ("logging", "level"): "LOG_LEVEL",
    ("logging", "log_thinking"): "LOG_THINKING",
    ("logging", "max_size_mb"): "LOG_MAX_SIZE_MB",
    ("logging", "tty_enabled"): "LOG_TTY_ENABLED",
    ("mcp", "config_path"): "MCP_CONFIG_PATH",
    ("models", "agent", "api_key"): "AGENT_MODEL_API_KEY",
    ("models", "agent", "api_mode"): "AGENT_MODEL_API_MODE",
    ("models", "agent", "api_url"): "AGENT_MODEL_API_URL",
    ("models", "agent", "context_window_tokens"): "AGENT_MODEL_CONTEXT_WINDOW_TOKENS",
    ("models", "agent", "model_name"): "AGENT_MODEL_NAME",
    (
        "models",
        "agent",
        "reasoning_content_replay",
    ): "AGENT_MODEL_REASONING_CONTENT_REPLAY",
    (
        "models",
        "agent",
        "responses_force_stateless_replay",
    ): "AGENT_MODEL_RESPONSES_FORCE_STATELESS_REPLAY",
    (
        "models",
        "agent",
        "responses_tool_choice_compat",
    ): "AGENT_MODEL_RESPONSES_TOOL_CHOICE_COMPAT",
    ("models", "agent", "system_prompt_as_user"): "AGENT_MODEL_SYSTEM_PROMPT_AS_USER",
    ("models", "chat", "api_key"): "CHAT_MODEL_API_KEY",
    ("models", "chat", "api_mode"): "CHAT_MODEL_API_MODE",
    ("models", "chat", "api_url"): "CHAT_MODEL_API_URL",
    ("models", "chat", "context_window_tokens"): "CHAT_MODEL_CONTEXT_WINDOW_TOKENS",
    ("models", "chat", "max_tokens"): "CHAT_MODEL_MAX_TOKENS",
    ("models", "chat", "model_name"): "CHAT_MODEL_NAME",
    (
        "models",
        "chat",
        "reasoning_content_replay",
    ): "CHAT_MODEL_REASONING_CONTENT_REPLAY",
    (
        "models",
        "chat",
        "responses_force_stateless_replay",
    ): "CHAT_MODEL_RESPONSES_FORCE_STATELESS_REPLAY",
    (
        "models",
        "chat",
        "responses_tool_choice_compat",
    ): "CHAT_MODEL_RESPONSES_TOOL_CHOICE_COMPAT",
    ("models", "chat", "system_prompt_as_user"): "CHAT_MODEL_SYSTEM_PROMPT_AS_USER",
    (
        "models",
        "embedding",
        "context_window_tokens",
    ): "EMBEDDING_MODEL_CONTEXT_WINDOW_TOKENS",
    ("models", "grok", "api_key"): "GROK_MODEL_API_KEY",
    ("models", "grok", "api_url"): "GROK_MODEL_API_URL",
    ("models", "grok", "context_window_tokens"): "GROK_MODEL_CONTEXT_WINDOW_TOKENS",
    ("models", "grok", "max_tokens"): "GROK_MODEL_MAX_TOKENS",
    ("models", "grok", "model_name"): "GROK_MODEL_NAME",
    ("models", "naga", "api_key"): "NAGA_MODEL_API_KEY",
    ("models", "naga", "api_mode"): "NAGA_MODEL_API_MODE",
    ("models", "naga", "api_url"): "NAGA_MODEL_API_URL",
    ("models", "naga", "context_window_tokens"): "NAGA_MODEL_CONTEXT_WINDOW_TOKENS",
    ("models", "naga", "model_name"): "NAGA_MODEL_NAME",
    (
        "models",
        "naga",
        "reasoning_content_replay",
    ): "NAGA_MODEL_REASONING_CONTENT_REPLAY",
    (
        "models",
        "naga",
        "responses_force_stateless_replay",
    ): "NAGA_MODEL_RESPONSES_FORCE_STATELESS_REPLAY",
    (
        "models",
        "naga",
        "responses_tool_choice_compat",
    ): "NAGA_MODEL_RESPONSES_TOOL_CHOICE_COMPAT",
    ("models", "naga", "system_prompt_as_user"): "NAGA_MODEL_SYSTEM_PROMPT_AS_USER",
    ("models", "rerank", "api_key"): "RERANK_MODEL_API_KEY",
    ("models", "rerank", "api_url"): "RERANK_MODEL_API_URL",
    ("models", "rerank", "context_window_tokens"): "RERANK_MODEL_CONTEXT_WINDOW_TOKENS",
    ("models", "rerank", "model_name"): "RERANK_MODEL_NAME",
    ("models", "security", "api_key"): "SECURITY_MODEL_API_KEY",
    ("models", "security", "api_mode"): "SECURITY_MODEL_API_MODE",
    ("models", "security", "api_url"): "SECURITY_MODEL_API_URL",
    (
        "models",
        "security",
        "context_window_tokens",
    ): "SECURITY_MODEL_CONTEXT_WINDOW_TOKENS",
    ("models", "security", "model_name"): "SECURITY_MODEL_NAME",
    (
        "models",
        "security",
        "reasoning_content_replay",
    ): "SECURITY_MODEL_REASONING_CONTENT_REPLAY",
    (
        "models",
        "security",
        "responses_force_stateless_replay",
    ): "SECURITY_MODEL_RESPONSES_FORCE_STATELESS_REPLAY",
    (
        "models",
        "security",
        "responses_tool_choice_compat",
    ): "SECURITY_MODEL_RESPONSES_TOOL_CHOICE_COMPAT",
    (
        "models",
        "security",
        "system_prompt_as_user",
    ): "SECURITY_MODEL_SYSTEM_PROMPT_AS_USER",
    ("models", "vision", "api_key"): "VISION_MODEL_API_KEY",
    ("models", "vision", "api_mode"): "VISION_MODEL_API_MODE",
    ("models", "vision", "api_url"): "VISION_MODEL_API_URL",
    ("models", "vision", "context_window_tokens"): "VISION_MODEL_CONTEXT_WINDOW_TOKENS",
    ("models", "vision", "model_name"): "VISION_MODEL_NAME",
    (
        "models",
        "vision",
        "reasoning_content_replay",
    ): "VISION_MODEL_REASONING_CONTENT_REPLAY",
    (
        "models",
        "vision",
        "responses_force_stateless_replay",
    ): "VISION_MODEL_RESPONSES_FORCE_STATELESS_REPLAY",
    (
        "models",
        "vision",
        "responses_tool_choice_compat",
    ): "VISION_MODEL_RESPONSES_TOOL_CHOICE_COMPAT",
    ("models", "vision", "system_prompt_as_user"): "VISION_MODEL_SYSTEM_PROMPT_AS_USER",
    ("onebot", "token"): "ONEBOT_TOKEN",
    ("onebot", "ws_url"): "ONEBOT_WS_URL",
    ("proxy", "use_proxy"): "USE_PROXY",
    ("search", "firecrawl", "api_key"): "FIRECRAWL_API_KEY",
    ("search", "firecrawl", "base_url"): "FIRECRAWL_BASE_URL",
    ("search", "firecrawl", "enabled"): "FIRECRAWL_SEARCH_ENABLED",
    ("search", "priority"): "SEARCH_PRIORITY",
    ("search", "searxng_url"): "SEARXNG_URL",
    ("skills", "hot_reload"): "SKILLS_HOT_RELOAD",
    ("skills", "intro_hash_path"): "AGENT_INTRO_HASH_PATH",
    ("skills", "prefetch_tools_hide"): "PREFETCH_TOOLS_HIDE",
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
