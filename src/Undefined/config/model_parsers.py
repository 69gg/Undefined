"""Model configuration parsers extracted from Config class."""

from __future__ import annotations

import logging
from typing import Any

from Undefined.utils.request_params import merge_request_params

from .admin import load_local_admins
from .coercers import (
    _coerce_bool,
    _coerce_float,
    _coerce_int,
    _coerce_str,
    _get_model_request_params,
    _get_value,
    _normalize_queue_interval,
    _VALID_API_MODES,
)
from .models import (
    AgentModelConfig,
    ChatModelConfig,
    EmbeddingModelConfig,
    GrokModelConfig,
    ImageGenConfig,
    ImageGenModelConfig,
    ModelPool,
    ModelPoolEntry,
    RerankModelConfig,
    SecurityModelConfig,
    VisionModelConfig,
)
from .resolvers import (
    _resolve_api_mode,
    _resolve_reasoning_effort,
    _resolve_reasoning_effort_style,
    _resolve_responses_force_stateless_replay,
    _resolve_responses_tool_choice_compat,
    _resolve_thinking_compat_flags,
)

logger = logging.getLogger(__name__)


def _parse_model_pool(
    data: dict[str, Any],
    model_section: str,
    primary_config: ChatModelConfig | AgentModelConfig,
) -> ModelPool | None:
    """解析模型池配置，缺省字段继承 primary_config"""
    pool_data = data.get("models", {}).get(model_section, {}).get("pool")
    if not isinstance(pool_data, dict):
        return None

    enabled = _coerce_bool(pool_data.get("enabled"), False)
    strategy = _coerce_str(pool_data.get("strategy"), "default").strip().lower()
    if strategy not in ("default", "round_robin", "random"):
        strategy = "default"

    raw_models = pool_data.get("models")
    if not isinstance(raw_models, list):
        return ModelPool(enabled=enabled, strategy=strategy)

    entries: list[ModelPoolEntry] = []
    for item in raw_models:
        if not isinstance(item, dict):
            continue
        name = _coerce_str(item.get("model_name"), "").strip()
        if not name:
            continue
        entries.append(
            ModelPoolEntry(
                api_url=_coerce_str(item.get("api_url"), primary_config.api_url),
                api_key=_coerce_str(item.get("api_key"), primary_config.api_key),
                model_name=name,
                max_tokens=_coerce_int(
                    item.get("max_tokens"), primary_config.max_tokens
                ),
                queue_interval_seconds=_normalize_queue_interval(
                    _coerce_float(
                        item.get("queue_interval_seconds"),
                        primary_config.queue_interval_seconds,
                    ),
                    primary_config.queue_interval_seconds,
                ),
                api_mode=(
                    _coerce_str(item.get("api_mode"), primary_config.api_mode)
                    .strip()
                    .lower()
                )
                if _coerce_str(item.get("api_mode"), primary_config.api_mode)
                .strip()
                .lower()
                in _VALID_API_MODES
                else primary_config.api_mode,
                thinking_enabled=_coerce_bool(
                    item.get("thinking_enabled"), primary_config.thinking_enabled
                ),
                thinking_budget_tokens=_coerce_int(
                    item.get("thinking_budget_tokens"),
                    primary_config.thinking_budget_tokens,
                ),
                thinking_include_budget=_coerce_bool(
                    item.get("thinking_include_budget"),
                    primary_config.thinking_include_budget,
                ),
                reasoning_effort_style=_resolve_reasoning_effort_style(
                    item.get("reasoning_effort_style"),
                    primary_config.reasoning_effort_style,
                ),
                thinking_tool_call_compat=_coerce_bool(
                    item.get("thinking_tool_call_compat"),
                    primary_config.thinking_tool_call_compat,
                ),
                responses_tool_choice_compat=_coerce_bool(
                    item.get("responses_tool_choice_compat"),
                    primary_config.responses_tool_choice_compat,
                ),
                responses_force_stateless_replay=_coerce_bool(
                    item.get("responses_force_stateless_replay"),
                    primary_config.responses_force_stateless_replay,
                ),
                prompt_cache_enabled=_coerce_bool(
                    item.get("prompt_cache_enabled"),
                    primary_config.prompt_cache_enabled,
                ),
                reasoning_enabled=_coerce_bool(
                    item.get("reasoning_enabled"),
                    primary_config.reasoning_enabled,
                ),
                reasoning_effort=_resolve_reasoning_effort(
                    item.get("reasoning_effort"),
                    primary_config.reasoning_effort,
                ),
                request_params=merge_request_params(
                    primary_config.request_params,
                    item.get("request_params"),
                ),
            )
        )

    return ModelPool(enabled=enabled, strategy=strategy, models=entries)


def _parse_embedding_model_config(data: dict[str, Any]) -> EmbeddingModelConfig:
    return EmbeddingModelConfig(
        api_url=_coerce_str(
            _get_value(
                data, ("models", "embedding", "api_url"), "EMBEDDING_MODEL_API_URL"
            ),
            "",
        ),
        api_key=_coerce_str(
            _get_value(
                data, ("models", "embedding", "api_key"), "EMBEDDING_MODEL_API_KEY"
            ),
            "",
        ),
        model_name=_coerce_str(
            _get_value(
                data, ("models", "embedding", "model_name"), "EMBEDDING_MODEL_NAME"
            ),
            "",
        ),
        queue_interval_seconds=_normalize_queue_interval(
            _coerce_float(
                _get_value(
                    data, ("models", "embedding", "queue_interval_seconds"), None
                ),
                0.0,
            ),
            0.0,
        ),
        dimensions=_coerce_int(
            _get_value(data, ("models", "embedding", "dimensions"), None), 0
        )
        or None,
        query_instruction=_coerce_str(
            _get_value(data, ("models", "embedding", "query_instruction"), None), ""
        ),
        document_instruction=_coerce_str(
            _get_value(data, ("models", "embedding", "document_instruction"), None),
            "",
        ),
        request_params=_get_model_request_params(data, "embedding"),
    )


def _parse_rerank_model_config(data: dict[str, Any]) -> RerankModelConfig:
    queue_interval_seconds = _normalize_queue_interval(
        _coerce_float(
            _get_value(data, ("models", "rerank", "queue_interval_seconds"), None),
            0.0,
        ),
        0.0,
    )
    return RerankModelConfig(
        api_url=_coerce_str(
            _get_value(data, ("models", "rerank", "api_url"), "RERANK_MODEL_API_URL"),
            "",
        ),
        api_key=_coerce_str(
            _get_value(data, ("models", "rerank", "api_key"), "RERANK_MODEL_API_KEY"),
            "",
        ),
        model_name=_coerce_str(
            _get_value(data, ("models", "rerank", "model_name"), "RERANK_MODEL_NAME"),
            "",
        ),
        queue_interval_seconds=queue_interval_seconds,
        query_instruction=_coerce_str(
            _get_value(data, ("models", "rerank", "query_instruction"), None), ""
        ),
        request_params=_get_model_request_params(data, "rerank"),
    )


def _parse_chat_model_config(data: dict[str, Any]) -> ChatModelConfig:
    queue_interval_seconds = _normalize_queue_interval(
        _coerce_float(
            _get_value(
                data,
                ("models", "chat", "queue_interval_seconds"),
                "CHAT_MODEL_QUEUE_INTERVAL",
            ),
            1.0,
        )
    )
    thinking_include_budget, thinking_tool_call_compat = _resolve_thinking_compat_flags(
        data=data,
        model_name="chat",
        include_budget_env_key="CHAT_MODEL_THINKING_INCLUDE_BUDGET",
        tool_call_compat_env_key="CHAT_MODEL_THINKING_TOOL_CALL_COMPAT",
        legacy_env_key="CHAT_MODEL_DEEPSEEK_NEW_COT_SUPPORT",
    )
    api_mode = _resolve_api_mode(data, "chat", "CHAT_MODEL_API_MODE")
    responses_tool_choice_compat = _resolve_responses_tool_choice_compat(
        data, "chat", "CHAT_MODEL_RESPONSES_TOOL_CHOICE_COMPAT"
    )
    responses_force_stateless_replay = _resolve_responses_force_stateless_replay(
        data, "chat", "CHAT_MODEL_RESPONSES_FORCE_STATELESS_REPLAY"
    )
    prompt_cache_enabled = _coerce_bool(
        _get_value(
            data,
            ("models", "chat", "prompt_cache_enabled"),
            "CHAT_MODEL_PROMPT_CACHE_ENABLED",
        ),
        True,
    )
    reasoning_enabled = _coerce_bool(
        _get_value(
            data,
            ("models", "chat", "reasoning_enabled"),
            "CHAT_MODEL_REASONING_ENABLED",
        ),
        False,
    )
    reasoning_effort = _resolve_reasoning_effort(
        _get_value(
            data,
            ("models", "chat", "reasoning_effort"),
            "CHAT_MODEL_REASONING_EFFORT",
        ),
        "medium",
    )
    config = ChatModelConfig(
        api_url=_coerce_str(
            _get_value(data, ("models", "chat", "api_url"), "CHAT_MODEL_API_URL"),
            "",
        ),
        api_key=_coerce_str(
            _get_value(data, ("models", "chat", "api_key"), "CHAT_MODEL_API_KEY"),
            "",
        ),
        model_name=_coerce_str(
            _get_value(data, ("models", "chat", "model_name"), "CHAT_MODEL_NAME"),
            "",
        ),
        max_tokens=_coerce_int(
            _get_value(data, ("models", "chat", "max_tokens"), "CHAT_MODEL_MAX_TOKENS"),
            8192,
        ),
        queue_interval_seconds=queue_interval_seconds,
        api_mode=api_mode,
        thinking_enabled=_coerce_bool(
            _get_value(
                data,
                ("models", "chat", "thinking_enabled"),
                "CHAT_MODEL_THINKING_ENABLED",
            ),
            False,
        ),
        thinking_budget_tokens=_coerce_int(
            _get_value(
                data,
                ("models", "chat", "thinking_budget_tokens"),
                "CHAT_MODEL_THINKING_BUDGET_TOKENS",
            ),
            20000,
        ),
        thinking_include_budget=thinking_include_budget,
        reasoning_effort_style=_resolve_reasoning_effort_style(
            _get_value(
                data,
                ("models", "chat", "reasoning_effort_style"),
                "CHAT_MODEL_REASONING_EFFORT_STYLE",
            ),
        ),
        thinking_tool_call_compat=thinking_tool_call_compat,
        responses_tool_choice_compat=responses_tool_choice_compat,
        responses_force_stateless_replay=responses_force_stateless_replay,
        prompt_cache_enabled=prompt_cache_enabled,
        reasoning_enabled=reasoning_enabled,
        reasoning_effort=reasoning_effort,
        request_params=_get_model_request_params(data, "chat"),
    )
    config.pool = _parse_model_pool(data, "chat", config)
    return config


def _parse_vision_model_config(data: dict[str, Any]) -> VisionModelConfig:
    queue_interval_seconds = _normalize_queue_interval(
        _coerce_float(
            _get_value(
                data,
                ("models", "vision", "queue_interval_seconds"),
                "VISION_MODEL_QUEUE_INTERVAL",
            ),
            1.0,
        )
    )
    thinking_include_budget, thinking_tool_call_compat = _resolve_thinking_compat_flags(
        data=data,
        model_name="vision",
        include_budget_env_key="VISION_MODEL_THINKING_INCLUDE_BUDGET",
        tool_call_compat_env_key="VISION_MODEL_THINKING_TOOL_CALL_COMPAT",
        legacy_env_key="VISION_MODEL_DEEPSEEK_NEW_COT_SUPPORT",
    )
    api_mode = _resolve_api_mode(data, "vision", "VISION_MODEL_API_MODE")
    responses_tool_choice_compat = _resolve_responses_tool_choice_compat(
        data, "vision", "VISION_MODEL_RESPONSES_TOOL_CHOICE_COMPAT"
    )
    responses_force_stateless_replay = _resolve_responses_force_stateless_replay(
        data, "vision", "VISION_MODEL_RESPONSES_FORCE_STATELESS_REPLAY"
    )
    prompt_cache_enabled = _coerce_bool(
        _get_value(
            data,
            ("models", "vision", "prompt_cache_enabled"),
            "VISION_MODEL_PROMPT_CACHE_ENABLED",
        ),
        True,
    )
    reasoning_enabled = _coerce_bool(
        _get_value(
            data,
            ("models", "vision", "reasoning_enabled"),
            "VISION_MODEL_REASONING_ENABLED",
        ),
        False,
    )
    reasoning_effort = _resolve_reasoning_effort(
        _get_value(
            data,
            ("models", "vision", "reasoning_effort"),
            "VISION_MODEL_REASONING_EFFORT",
        ),
        "medium",
    )
    return VisionModelConfig(
        api_url=_coerce_str(
            _get_value(data, ("models", "vision", "api_url"), "VISION_MODEL_API_URL"),
            "",
        ),
        api_key=_coerce_str(
            _get_value(data, ("models", "vision", "api_key"), "VISION_MODEL_API_KEY"),
            "",
        ),
        model_name=_coerce_str(
            _get_value(data, ("models", "vision", "model_name"), "VISION_MODEL_NAME"),
            "",
        ),
        queue_interval_seconds=queue_interval_seconds,
        api_mode=api_mode,
        thinking_enabled=_coerce_bool(
            _get_value(
                data,
                ("models", "vision", "thinking_enabled"),
                "VISION_MODEL_THINKING_ENABLED",
            ),
            False,
        ),
        thinking_budget_tokens=_coerce_int(
            _get_value(
                data,
                ("models", "vision", "thinking_budget_tokens"),
                "VISION_MODEL_THINKING_BUDGET_TOKENS",
            ),
            20000,
        ),
        thinking_include_budget=thinking_include_budget,
        reasoning_effort_style=_resolve_reasoning_effort_style(
            _get_value(
                data,
                ("models", "vision", "reasoning_effort_style"),
                "VISION_MODEL_REASONING_EFFORT_STYLE",
            ),
        ),
        thinking_tool_call_compat=thinking_tool_call_compat,
        responses_tool_choice_compat=responses_tool_choice_compat,
        responses_force_stateless_replay=responses_force_stateless_replay,
        prompt_cache_enabled=prompt_cache_enabled,
        reasoning_enabled=reasoning_enabled,
        reasoning_effort=reasoning_effort,
        request_params=_get_model_request_params(data, "vision"),
    )


def _parse_security_model_config(
    data: dict[str, Any], chat_model: ChatModelConfig
) -> SecurityModelConfig:
    api_url = _coerce_str(
        _get_value(data, ("models", "security", "api_url"), "SECURITY_MODEL_API_URL"),
        "",
    )
    api_key = _coerce_str(
        _get_value(data, ("models", "security", "api_key"), "SECURITY_MODEL_API_KEY"),
        "",
    )
    model_name = _coerce_str(
        _get_value(data, ("models", "security", "model_name"), "SECURITY_MODEL_NAME"),
        "",
    )
    queue_interval_seconds = _coerce_float(
        _get_value(
            data,
            ("models", "security", "queue_interval_seconds"),
            "SECURITY_MODEL_QUEUE_INTERVAL",
        ),
        1.0,
    )
    queue_interval_seconds = _normalize_queue_interval(queue_interval_seconds)

    thinking_include_budget, thinking_tool_call_compat = _resolve_thinking_compat_flags(
        data=data,
        model_name="security",
        include_budget_env_key="SECURITY_MODEL_THINKING_INCLUDE_BUDGET",
        tool_call_compat_env_key="SECURITY_MODEL_THINKING_TOOL_CALL_COMPAT",
        legacy_env_key="SECURITY_MODEL_DEEPSEEK_NEW_COT_SUPPORT",
    )
    api_mode = _resolve_api_mode(data, "security", "SECURITY_MODEL_API_MODE")
    responses_tool_choice_compat = _resolve_responses_tool_choice_compat(
        data, "security", "SECURITY_MODEL_RESPONSES_TOOL_CHOICE_COMPAT"
    )
    responses_force_stateless_replay = _resolve_responses_force_stateless_replay(
        data, "security", "SECURITY_MODEL_RESPONSES_FORCE_STATELESS_REPLAY"
    )
    prompt_cache_enabled = _coerce_bool(
        _get_value(
            data,
            ("models", "security", "prompt_cache_enabled"),
            "SECURITY_MODEL_PROMPT_CACHE_ENABLED",
        ),
        True,
    )
    reasoning_enabled = _coerce_bool(
        _get_value(
            data,
            ("models", "security", "reasoning_enabled"),
            "SECURITY_MODEL_REASONING_ENABLED",
        ),
        False,
    )
    reasoning_effort = _resolve_reasoning_effort(
        _get_value(
            data,
            ("models", "security", "reasoning_effort"),
            "SECURITY_MODEL_REASONING_EFFORT",
        ),
        "medium",
    )

    if api_url and api_key and model_name:
        return SecurityModelConfig(
            api_url=api_url,
            api_key=api_key,
            model_name=model_name,
            max_tokens=_coerce_int(
                _get_value(
                    data,
                    ("models", "security", "max_tokens"),
                    "SECURITY_MODEL_MAX_TOKENS",
                ),
                100,
            ),
            queue_interval_seconds=queue_interval_seconds,
            api_mode=api_mode,
            thinking_enabled=_coerce_bool(
                _get_value(
                    data,
                    ("models", "security", "thinking_enabled"),
                    "SECURITY_MODEL_THINKING_ENABLED",
                ),
                False,
            ),
            thinking_budget_tokens=_coerce_int(
                _get_value(
                    data,
                    ("models", "security", "thinking_budget_tokens"),
                    "SECURITY_MODEL_THINKING_BUDGET_TOKENS",
                ),
                0,
            ),
            thinking_include_budget=thinking_include_budget,
            reasoning_effort_style=_resolve_reasoning_effort_style(
                _get_value(
                    data,
                    ("models", "security", "reasoning_effort_style"),
                    "SECURITY_MODEL_REASONING_EFFORT_STYLE",
                ),
            ),
            thinking_tool_call_compat=thinking_tool_call_compat,
            responses_tool_choice_compat=responses_tool_choice_compat,
            responses_force_stateless_replay=responses_force_stateless_replay,
            prompt_cache_enabled=prompt_cache_enabled,
            reasoning_enabled=reasoning_enabled,
            reasoning_effort=reasoning_effort,
            request_params=_get_model_request_params(data, "security"),
        )

    logger.warning("未配置安全模型，将使用对话模型作为后备")
    return SecurityModelConfig(
        api_url=chat_model.api_url,
        api_key=chat_model.api_key,
        model_name=chat_model.model_name,
        max_tokens=chat_model.max_tokens,
        queue_interval_seconds=chat_model.queue_interval_seconds,
        api_mode=chat_model.api_mode,
        thinking_enabled=False,
        thinking_budget_tokens=0,
        thinking_include_budget=True,
        reasoning_effort_style="openai",
        thinking_tool_call_compat=chat_model.thinking_tool_call_compat,
        responses_tool_choice_compat=chat_model.responses_tool_choice_compat,
        responses_force_stateless_replay=chat_model.responses_force_stateless_replay,
        prompt_cache_enabled=chat_model.prompt_cache_enabled,
        reasoning_enabled=chat_model.reasoning_enabled,
        reasoning_effort=chat_model.reasoning_effort,
        request_params=merge_request_params(chat_model.request_params),
    )


def _parse_naga_model_config(
    data: dict[str, Any], security_model: SecurityModelConfig
) -> SecurityModelConfig:
    api_url = _coerce_str(
        _get_value(data, ("models", "naga", "api_url"), "NAGA_MODEL_API_URL"),
        "",
    )
    api_key = _coerce_str(
        _get_value(data, ("models", "naga", "api_key"), "NAGA_MODEL_API_KEY"),
        "",
    )
    model_name = _coerce_str(
        _get_value(data, ("models", "naga", "model_name"), "NAGA_MODEL_NAME"),
        "",
    )
    queue_interval_seconds = _coerce_float(
        _get_value(
            data,
            ("models", "naga", "queue_interval_seconds"),
            "NAGA_MODEL_QUEUE_INTERVAL",
        ),
        security_model.queue_interval_seconds,
    )
    queue_interval_seconds = _normalize_queue_interval(queue_interval_seconds)

    thinking_include_budget, thinking_tool_call_compat = _resolve_thinking_compat_flags(
        data=data,
        model_name="naga",
        include_budget_env_key="NAGA_MODEL_THINKING_INCLUDE_BUDGET",
        tool_call_compat_env_key="NAGA_MODEL_THINKING_TOOL_CALL_COMPAT",
        legacy_env_key="NAGA_MODEL_DEEPSEEK_NEW_COT_SUPPORT",
    )
    api_mode = _resolve_api_mode(data, "naga", "NAGA_MODEL_API_MODE")
    responses_tool_choice_compat = _resolve_responses_tool_choice_compat(
        data, "naga", "NAGA_MODEL_RESPONSES_TOOL_CHOICE_COMPAT"
    )
    responses_force_stateless_replay = _resolve_responses_force_stateless_replay(
        data, "naga", "NAGA_MODEL_RESPONSES_FORCE_STATELESS_REPLAY"
    )
    prompt_cache_enabled = _coerce_bool(
        _get_value(
            data,
            ("models", "naga", "prompt_cache_enabled"),
            "NAGA_MODEL_PROMPT_CACHE_ENABLED",
        ),
        getattr(security_model, "prompt_cache_enabled", True),
    )
    reasoning_enabled = _coerce_bool(
        _get_value(
            data,
            ("models", "naga", "reasoning_enabled"),
            "NAGA_MODEL_REASONING_ENABLED",
        ),
        getattr(security_model, "reasoning_enabled", False),
    )
    reasoning_effort = _resolve_reasoning_effort(
        _get_value(
            data,
            ("models", "naga", "reasoning_effort"),
            "NAGA_MODEL_REASONING_EFFORT",
        ),
        getattr(security_model, "reasoning_effort", "medium"),
    )

    if api_url and api_key and model_name:
        return SecurityModelConfig(
            api_url=api_url,
            api_key=api_key,
            model_name=model_name,
            max_tokens=_coerce_int(
                _get_value(
                    data,
                    ("models", "naga", "max_tokens"),
                    "NAGA_MODEL_MAX_TOKENS",
                ),
                160,
            ),
            queue_interval_seconds=queue_interval_seconds,
            api_mode=api_mode,
            thinking_enabled=_coerce_bool(
                _get_value(
                    data,
                    ("models", "naga", "thinking_enabled"),
                    "NAGA_MODEL_THINKING_ENABLED",
                ),
                False,
            ),
            thinking_budget_tokens=_coerce_int(
                _get_value(
                    data,
                    ("models", "naga", "thinking_budget_tokens"),
                    "NAGA_MODEL_THINKING_BUDGET_TOKENS",
                ),
                0,
            ),
            thinking_include_budget=thinking_include_budget,
            reasoning_effort_style=_resolve_reasoning_effort_style(
                _get_value(
                    data,
                    ("models", "naga", "reasoning_effort_style"),
                    "NAGA_MODEL_REASONING_EFFORT_STYLE",
                ),
            ),
            thinking_tool_call_compat=thinking_tool_call_compat,
            responses_tool_choice_compat=responses_tool_choice_compat,
            responses_force_stateless_replay=responses_force_stateless_replay,
            prompt_cache_enabled=prompt_cache_enabled,
            reasoning_enabled=reasoning_enabled,
            reasoning_effort=reasoning_effort,
            request_params=_get_model_request_params(data, "naga"),
        )

    logger.info(
        "未配置 Naga 审核模型，将使用已解析的安全模型配置作为后备（安全模型本身可能已回退）"
    )
    return SecurityModelConfig(
        api_url=security_model.api_url,
        api_key=security_model.api_key,
        model_name=security_model.model_name,
        max_tokens=security_model.max_tokens,
        queue_interval_seconds=security_model.queue_interval_seconds,
        api_mode=security_model.api_mode,
        thinking_enabled=security_model.thinking_enabled,
        thinking_budget_tokens=security_model.thinking_budget_tokens,
        thinking_include_budget=security_model.thinking_include_budget,
        reasoning_effort_style=security_model.reasoning_effort_style,
        thinking_tool_call_compat=security_model.thinking_tool_call_compat,
        responses_tool_choice_compat=security_model.responses_tool_choice_compat,
        responses_force_stateless_replay=security_model.responses_force_stateless_replay,
        prompt_cache_enabled=security_model.prompt_cache_enabled,
        reasoning_enabled=security_model.reasoning_enabled,
        reasoning_effort=security_model.reasoning_effort,
        request_params=merge_request_params(security_model.request_params),
    )


def _parse_agent_model_config(data: dict[str, Any]) -> AgentModelConfig:
    queue_interval_seconds = _normalize_queue_interval(
        _coerce_float(
            _get_value(
                data,
                ("models", "agent", "queue_interval_seconds"),
                "AGENT_MODEL_QUEUE_INTERVAL",
            ),
            1.0,
        )
    )
    thinking_include_budget, thinking_tool_call_compat = _resolve_thinking_compat_flags(
        data=data,
        model_name="agent",
        include_budget_env_key="AGENT_MODEL_THINKING_INCLUDE_BUDGET",
        tool_call_compat_env_key="AGENT_MODEL_THINKING_TOOL_CALL_COMPAT",
        legacy_env_key="AGENT_MODEL_DEEPSEEK_NEW_COT_SUPPORT",
    )
    api_mode = _resolve_api_mode(data, "agent", "AGENT_MODEL_API_MODE")
    responses_tool_choice_compat = _resolve_responses_tool_choice_compat(
        data, "agent", "AGENT_MODEL_RESPONSES_TOOL_CHOICE_COMPAT"
    )
    responses_force_stateless_replay = _resolve_responses_force_stateless_replay(
        data, "agent", "AGENT_MODEL_RESPONSES_FORCE_STATELESS_REPLAY"
    )
    prompt_cache_enabled = _coerce_bool(
        _get_value(
            data,
            ("models", "agent", "prompt_cache_enabled"),
            "AGENT_MODEL_PROMPT_CACHE_ENABLED",
        ),
        True,
    )
    reasoning_enabled = _coerce_bool(
        _get_value(
            data,
            ("models", "agent", "reasoning_enabled"),
            "AGENT_MODEL_REASONING_ENABLED",
        ),
        False,
    )
    reasoning_effort = _resolve_reasoning_effort(
        _get_value(
            data,
            ("models", "agent", "reasoning_effort"),
            "AGENT_MODEL_REASONING_EFFORT",
        ),
        "medium",
    )
    config = AgentModelConfig(
        api_url=_coerce_str(
            _get_value(data, ("models", "agent", "api_url"), "AGENT_MODEL_API_URL"),
            "",
        ),
        api_key=_coerce_str(
            _get_value(data, ("models", "agent", "api_key"), "AGENT_MODEL_API_KEY"),
            "",
        ),
        model_name=_coerce_str(
            _get_value(data, ("models", "agent", "model_name"), "AGENT_MODEL_NAME"),
            "",
        ),
        max_tokens=_coerce_int(
            _get_value(
                data, ("models", "agent", "max_tokens"), "AGENT_MODEL_MAX_TOKENS"
            ),
            4096,
        ),
        queue_interval_seconds=queue_interval_seconds,
        api_mode=api_mode,
        thinking_enabled=_coerce_bool(
            _get_value(
                data,
                ("models", "agent", "thinking_enabled"),
                "AGENT_MODEL_THINKING_ENABLED",
            ),
            False,
        ),
        thinking_budget_tokens=_coerce_int(
            _get_value(
                data,
                ("models", "agent", "thinking_budget_tokens"),
                "AGENT_MODEL_THINKING_BUDGET_TOKENS",
            ),
            0,
        ),
        thinking_include_budget=thinking_include_budget,
        reasoning_effort_style=_resolve_reasoning_effort_style(
            _get_value(
                data,
                ("models", "agent", "reasoning_effort_style"),
                "AGENT_MODEL_REASONING_EFFORT_STYLE",
            ),
        ),
        thinking_tool_call_compat=thinking_tool_call_compat,
        responses_tool_choice_compat=responses_tool_choice_compat,
        responses_force_stateless_replay=responses_force_stateless_replay,
        prompt_cache_enabled=prompt_cache_enabled,
        reasoning_enabled=reasoning_enabled,
        reasoning_effort=reasoning_effort,
        request_params=_get_model_request_params(data, "agent"),
    )
    config.pool = _parse_model_pool(data, "agent", config)
    return config


def _parse_grok_model_config(data: dict[str, Any]) -> GrokModelConfig:
    queue_interval_seconds = _normalize_queue_interval(
        _coerce_float(
            _get_value(
                data,
                ("models", "grok", "queue_interval_seconds"),
                "GROK_MODEL_QUEUE_INTERVAL",
            ),
            1.0,
        )
    )
    return GrokModelConfig(
        api_url=_coerce_str(
            _get_value(data, ("models", "grok", "api_url"), "GROK_MODEL_API_URL"),
            "",
        ),
        api_key=_coerce_str(
            _get_value(data, ("models", "grok", "api_key"), "GROK_MODEL_API_KEY"),
            "",
        ),
        model_name=_coerce_str(
            _get_value(data, ("models", "grok", "model_name"), "GROK_MODEL_NAME"),
            "",
        ),
        max_tokens=_coerce_int(
            _get_value(data, ("models", "grok", "max_tokens"), "GROK_MODEL_MAX_TOKENS"),
            8192,
        ),
        queue_interval_seconds=queue_interval_seconds,
        thinking_enabled=_coerce_bool(
            _get_value(
                data,
                ("models", "grok", "thinking_enabled"),
                "GROK_MODEL_THINKING_ENABLED",
            ),
            False,
        ),
        thinking_budget_tokens=_coerce_int(
            _get_value(
                data,
                ("models", "grok", "thinking_budget_tokens"),
                "GROK_MODEL_THINKING_BUDGET_TOKENS",
            ),
            20000,
        ),
        thinking_include_budget=_coerce_bool(
            _get_value(
                data,
                ("models", "grok", "thinking_include_budget"),
                "GROK_MODEL_THINKING_INCLUDE_BUDGET",
            ),
            True,
        ),
        reasoning_effort_style=_resolve_reasoning_effort_style(
            _get_value(
                data,
                ("models", "grok", "reasoning_effort_style"),
                "GROK_MODEL_REASONING_EFFORT_STYLE",
            ),
        ),
        prompt_cache_enabled=_coerce_bool(
            _get_value(
                data,
                ("models", "grok", "prompt_cache_enabled"),
                "GROK_MODEL_PROMPT_CACHE_ENABLED",
            ),
            True,
        ),
        reasoning_enabled=_coerce_bool(
            _get_value(
                data,
                ("models", "grok", "reasoning_enabled"),
                "GROK_MODEL_REASONING_ENABLED",
            ),
            False,
        ),
        reasoning_effort=_resolve_reasoning_effort(
            _get_value(
                data,
                ("models", "grok", "reasoning_effort"),
                "GROK_MODEL_REASONING_EFFORT",
            ),
            "medium",
        ),
        request_params=_get_model_request_params(data, "grok"),
    )


def _parse_image_gen_model_config(data: dict[str, Any]) -> ImageGenModelConfig:
    """解析 [models.image_gen] 生图模型配置"""
    return ImageGenModelConfig(
        api_url=_coerce_str(
            _get_value(
                data, ("models", "image_gen", "api_url"), "IMAGE_GEN_MODEL_API_URL"
            ),
            "",
        ),
        api_key=_coerce_str(
            _get_value(
                data, ("models", "image_gen", "api_key"), "IMAGE_GEN_MODEL_API_KEY"
            ),
            "",
        ),
        model_name=_coerce_str(
            _get_value(
                data, ("models", "image_gen", "model_name"), "IMAGE_GEN_MODEL_NAME"
            ),
            "",
        ),
        request_params=_get_model_request_params(data, "image_gen"),
    )


def _parse_image_edit_model_config(data: dict[str, Any]) -> ImageGenModelConfig:
    """解析 [models.image_edit] 参考图生图模型配置"""
    return ImageGenModelConfig(
        api_url=_coerce_str(
            _get_value(
                data,
                ("models", "image_edit", "api_url"),
                "IMAGE_EDIT_MODEL_API_URL",
            ),
            "",
        ),
        api_key=_coerce_str(
            _get_value(
                data,
                ("models", "image_edit", "api_key"),
                "IMAGE_EDIT_MODEL_API_KEY",
            ),
            "",
        ),
        model_name=_coerce_str(
            _get_value(
                data,
                ("models", "image_edit", "model_name"),
                "IMAGE_EDIT_MODEL_NAME",
            ),
            "",
        ),
        request_params=_get_model_request_params(data, "image_edit"),
    )


def _parse_image_gen_config(data: dict[str, Any]) -> ImageGenConfig:
    """解析 [image_gen] 生图工具配置"""
    return ImageGenConfig(
        provider=_coerce_str(
            _get_value(data, ("image_gen", "provider"), "IMAGE_GEN_PROVIDER"),
            "xingzhige",
        ),
        xingzhige_size=_coerce_str(
            _get_value(data, ("image_gen", "xingzhige_size"), None), "1:1"
        ),
        openai_size=_coerce_str(
            _get_value(data, ("image_gen", "openai_size"), None), ""
        ),
        openai_quality=_coerce_str(
            _get_value(data, ("image_gen", "openai_quality"), None), ""
        ),
        openai_style=_coerce_str(
            _get_value(data, ("image_gen", "openai_style"), None), ""
        ),
        openai_timeout=_coerce_float(
            _get_value(data, ("image_gen", "openai_timeout"), None), 120.0
        ),
    )


def _merge_admins(superadmin_qq: int, admin_qqs: list[int]) -> tuple[int, list[int]]:
    local_admins = load_local_admins()
    all_admins = list(set(admin_qqs + local_admins))
    if superadmin_qq and superadmin_qq not in all_admins:
        all_admins.append(superadmin_qq)
    return superadmin_qq, all_admins


def _verify_required_fields(
    bot_qq: int,
    superadmin_qq: int,
    onebot_ws_url: str,
    chat_model: ChatModelConfig,
    vision_model: VisionModelConfig,
    agent_model: AgentModelConfig,
    knowledge_enabled: bool,
    embedding_model: EmbeddingModelConfig,
) -> None:
    missing: list[str] = []
    if bot_qq <= 0:
        missing.append("core.bot_qq")
    if superadmin_qq <= 0:
        missing.append("core.superadmin_qq")
    if not onebot_ws_url:
        missing.append("onebot.ws_url")
    if not chat_model.api_url:
        missing.append("models.chat.api_url")
    if not chat_model.api_key:
        missing.append("models.chat.api_key")
    if not chat_model.model_name:
        missing.append("models.chat.model_name")
    if not vision_model.api_url:
        missing.append("models.vision.api_url")
    if not vision_model.api_key:
        missing.append("models.vision.api_key")
    if not vision_model.model_name:
        missing.append("models.vision.model_name")
    if not agent_model.api_url:
        missing.append("models.agent.api_url")
    if not agent_model.api_key:
        missing.append("models.agent.api_key")
    if not agent_model.model_name:
        missing.append("models.agent.model_name")
    if knowledge_enabled:
        if not embedding_model.api_url:
            missing.append("models.embedding.api_url")
        if not embedding_model.model_name:
            missing.append("models.embedding.model_name")
    if missing:
        raise ValueError(f"缺少必需配置: {', '.join(missing)}")


def _log_debug_info(
    chat_model: ChatModelConfig,
    vision_model: VisionModelConfig,
    security_model: SecurityModelConfig,
    naga_model: SecurityModelConfig,
    agent_model: AgentModelConfig,
    summary_model: AgentModelConfig,
    grok_model: GrokModelConfig,
) -> None:
    configs: list[
        tuple[
            str,
            ChatModelConfig
            | VisionModelConfig
            | SecurityModelConfig
            | AgentModelConfig
            | GrokModelConfig,
        ]
    ] = [
        ("chat", chat_model),
        ("vision", vision_model),
        ("security", security_model),
        ("naga", naga_model),
        ("agent", agent_model),
        ("summary", summary_model),
        ("grok", grok_model),
    ]
    for name, cfg in configs:
        logger.debug(
            "[配置] %s_model=%s api_url=%s api_key_set=%s api_mode=%s thinking=%s reasoning=%s/%s cot_compat=%s responses_tool_choice_compat=%s responses_force_stateless_replay=%s",
            name,
            cfg.model_name,
            cfg.api_url,
            bool(cfg.api_key),
            getattr(cfg, "api_mode", "chat_completions"),
            cfg.thinking_enabled,
            getattr(cfg, "reasoning_enabled", False),
            getattr(cfg, "reasoning_effort", "medium"),
            getattr(cfg, "thinking_tool_call_compat", False),
            getattr(cfg, "responses_tool_choice_compat", False),
            getattr(cfg, "responses_force_stateless_replay", False),
        )


def _parse_historian_model_config(
    data: dict[str, Any], fallback: AgentModelConfig
) -> AgentModelConfig:
    h = data.get("models", {}).get("historian", {})
    if not isinstance(h, dict) or not h:
        return fallback
    queue_interval_seconds = _coerce_float(
        h.get("queue_interval_seconds"), fallback.queue_interval_seconds
    )
    queue_interval_seconds = _normalize_queue_interval(
        queue_interval_seconds, fallback.queue_interval_seconds
    )
    thinking_include_budget, thinking_tool_call_compat = _resolve_thinking_compat_flags(
        data={"models": {"historian": h}},
        model_name="historian",
        include_budget_env_key="HISTORIAN_MODEL_THINKING_INCLUDE_BUDGET",
        tool_call_compat_env_key="HISTORIAN_MODEL_THINKING_TOOL_CALL_COMPAT",
        legacy_env_key="HISTORIAN_MODEL_DEEPSEEK_NEW_COT_SUPPORT",
    )
    api_mode = _resolve_api_mode(
        {"models": {"historian": h}},
        "historian",
        "HISTORIAN_MODEL_API_MODE",
        fallback.api_mode,
    )
    responses_tool_choice_compat = _resolve_responses_tool_choice_compat(
        {"models": {"historian": h}},
        "historian",
        "HISTORIAN_MODEL_RESPONSES_TOOL_CHOICE_COMPAT",
        fallback.responses_tool_choice_compat,
    )
    responses_force_stateless_replay = _resolve_responses_force_stateless_replay(
        {"models": {"historian": h}},
        "historian",
        "HISTORIAN_MODEL_RESPONSES_FORCE_STATELESS_REPLAY",
        fallback.responses_force_stateless_replay,
    )
    prompt_cache_enabled = _coerce_bool(
        _get_value(
            {"models": {"historian": h}},
            ("models", "historian", "prompt_cache_enabled"),
            "HISTORIAN_MODEL_PROMPT_CACHE_ENABLED",
        ),
        fallback.prompt_cache_enabled,
    )
    return AgentModelConfig(
        api_url=_coerce_str(h.get("api_url"), fallback.api_url),
        api_key=_coerce_str(h.get("api_key"), fallback.api_key),
        model_name=_coerce_str(h.get("model_name"), fallback.model_name),
        max_tokens=_coerce_int(h.get("max_tokens"), fallback.max_tokens),
        queue_interval_seconds=queue_interval_seconds,
        api_mode=api_mode,
        thinking_enabled=_coerce_bool(
            h.get("thinking_enabled"), fallback.thinking_enabled
        ),
        thinking_budget_tokens=_coerce_int(
            h.get("thinking_budget_tokens"), fallback.thinking_budget_tokens
        ),
        thinking_include_budget=thinking_include_budget,
        reasoning_effort_style=_resolve_reasoning_effort_style(
            _get_value(
                {"models": {"historian": h}},
                ("models", "historian", "reasoning_effort_style"),
                "HISTORIAN_MODEL_REASONING_EFFORT_STYLE",
            ),
            fallback.reasoning_effort_style,
        ),
        thinking_tool_call_compat=thinking_tool_call_compat,
        responses_tool_choice_compat=responses_tool_choice_compat,
        responses_force_stateless_replay=responses_force_stateless_replay,
        prompt_cache_enabled=prompt_cache_enabled,
        reasoning_enabled=_coerce_bool(
            _get_value(
                {"models": {"historian": h}},
                ("models", "historian", "reasoning_enabled"),
                "HISTORIAN_MODEL_REASONING_ENABLED",
            ),
            fallback.reasoning_enabled,
        ),
        reasoning_effort=_resolve_reasoning_effort(
            _get_value(
                {"models": {"historian": h}},
                ("models", "historian", "reasoning_effort"),
                "HISTORIAN_MODEL_REASONING_EFFORT",
            ),
            fallback.reasoning_effort,
        ),
        request_params=merge_request_params(
            fallback.request_params,
            h.get("request_params"),
        ),
    )


def _parse_summary_model_config(
    data: dict[str, Any], fallback: AgentModelConfig
) -> tuple[AgentModelConfig, bool]:
    s = data.get("models", {}).get("summary", {})
    if not isinstance(s, dict) or not s:
        return fallback, False
    queue_interval_seconds = _coerce_float(
        s.get("queue_interval_seconds"), fallback.queue_interval_seconds
    )
    queue_interval_seconds = _normalize_queue_interval(
        queue_interval_seconds, fallback.queue_interval_seconds
    )
    thinking_include_budget, thinking_tool_call_compat = _resolve_thinking_compat_flags(
        data={"models": {"summary": s}},
        model_name="summary",
        include_budget_env_key="SUMMARY_MODEL_THINKING_INCLUDE_BUDGET",
        tool_call_compat_env_key="SUMMARY_MODEL_THINKING_TOOL_CALL_COMPAT",
        legacy_env_key="SUMMARY_MODEL_DEEPSEEK_NEW_COT_SUPPORT",
    )
    api_mode = _resolve_api_mode(
        {"models": {"summary": s}},
        "summary",
        "SUMMARY_MODEL_API_MODE",
        fallback.api_mode,
    )
    responses_tool_choice_compat = _resolve_responses_tool_choice_compat(
        {"models": {"summary": s}},
        "summary",
        "SUMMARY_MODEL_RESPONSES_TOOL_CHOICE_COMPAT",
        fallback.responses_tool_choice_compat,
    )
    responses_force_stateless_replay = _resolve_responses_force_stateless_replay(
        {"models": {"summary": s}},
        "summary",
        "SUMMARY_MODEL_RESPONSES_FORCE_STATELESS_REPLAY",
        fallback.responses_force_stateless_replay,
    )
    prompt_cache_enabled = _coerce_bool(
        _get_value(
            {"models": {"summary": s}},
            ("models", "summary", "prompt_cache_enabled"),
            "SUMMARY_MODEL_PROMPT_CACHE_ENABLED",
        ),
        fallback.prompt_cache_enabled,
    )
    return (
        AgentModelConfig(
            api_url=_coerce_str(s.get("api_url"), fallback.api_url),
            api_key=_coerce_str(s.get("api_key"), fallback.api_key),
            model_name=_coerce_str(s.get("model_name"), fallback.model_name),
            max_tokens=_coerce_int(s.get("max_tokens"), fallback.max_tokens),
            queue_interval_seconds=queue_interval_seconds,
            api_mode=api_mode,
            thinking_enabled=_coerce_bool(
                s.get("thinking_enabled"), fallback.thinking_enabled
            ),
            thinking_budget_tokens=_coerce_int(
                s.get("thinking_budget_tokens"), fallback.thinking_budget_tokens
            ),
            thinking_include_budget=thinking_include_budget,
            reasoning_effort_style=_resolve_reasoning_effort_style(
                _get_value(
                    {"models": {"summary": s}},
                    ("models", "summary", "reasoning_effort_style"),
                    "SUMMARY_MODEL_REASONING_EFFORT_STYLE",
                ),
                fallback.reasoning_effort_style,
            ),
            thinking_tool_call_compat=thinking_tool_call_compat,
            responses_tool_choice_compat=responses_tool_choice_compat,
            responses_force_stateless_replay=responses_force_stateless_replay,
            prompt_cache_enabled=prompt_cache_enabled,
            reasoning_enabled=_coerce_bool(
                _get_value(
                    {"models": {"summary": s}},
                    ("models", "summary", "reasoning_enabled"),
                    "SUMMARY_MODEL_REASONING_ENABLED",
                ),
                fallback.reasoning_enabled,
            ),
            reasoning_effort=_resolve_reasoning_effort(
                _get_value(
                    {"models": {"summary": s}},
                    ("models", "summary", "reasoning_effort"),
                    "SUMMARY_MODEL_REASONING_EFFORT",
                ),
                fallback.reasoning_effort,
            ),
            request_params=merge_request_params(
                fallback.request_params,
                s.get("request_params"),
            ),
        ),
        True,
    )
