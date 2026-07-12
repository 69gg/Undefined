"""Naga model parser."""

from __future__ import annotations

# 模型配置解析：原始 dict → ChatModelConfig 等 dataclass

import logging
from typing import Any

from Undefined.utils.request_params import merge_request_params

from ..coercers import (
    _coerce_bool,
    _coerce_float,
    _coerce_int,
    _coerce_str,
    _get_model_request_params,
    _get_value,
    _normalize_queue_interval,
)
from ..models import (
    SecurityModelConfig,
)
from ..resolvers import (
    _resolve_api_mode,
    _resolve_context_window_tokens,
    _resolve_reasoning_effort,
    _resolve_reasoning_content_replay,
    _resolve_responses_force_stateless_replay,
    _resolve_responses_tool_choice_compat,
    _resolve_system_prompt_as_user,
    _resolve_thinking_compat_flags,
)

logger = logging.getLogger(__name__)


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
    reasoning_content_replay = _resolve_reasoning_content_replay(
        data,
        "naga",
        "NAGA_MODEL_REASONING_CONTENT_REPLAY",
        default=security_model.reasoning_content_replay,
    )
    system_prompt_as_user = _resolve_system_prompt_as_user(
        data,
        "naga",
        "NAGA_MODEL_SYSTEM_PROMPT_AS_USER",
        default=security_model.system_prompt_as_user,
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
    stream_enabled = _coerce_bool(
        _get_value(
            data,
            ("models", "naga", "stream_enabled"),
            "NAGA_MODEL_STREAM_ENABLED",
        ),
        getattr(security_model, "stream_enabled", False),
    )
    use_proxy = _coerce_bool(
        _get_value(data, ("models", "naga", "use_proxy"), "NAGA_MODEL_USE_PROXY"),
        False,
    )

    if api_url and api_key and model_name:
        context_window_tokens = _resolve_context_window_tokens(
            data,
            "naga",
            "NAGA_MODEL_CONTEXT_WINDOW_TOKENS",
            default=security_model.context_window_tokens,
        )
        return SecurityModelConfig(
            api_url=api_url,
            api_key=api_key,
            model_name=model_name,
            use_proxy=use_proxy,
            max_tokens=_coerce_int(
                _get_value(
                    data,
                    ("models", "naga", "max_tokens"),
                    "NAGA_MODEL_MAX_TOKENS",
                ),
                160,
            ),
            context_window_tokens=context_window_tokens,
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
            thinking_tool_call_compat=thinking_tool_call_compat,
            reasoning_content_replay=reasoning_content_replay,
            system_prompt_as_user=system_prompt_as_user,
            responses_tool_choice_compat=responses_tool_choice_compat,
            responses_force_stateless_replay=responses_force_stateless_replay,
            prompt_cache_enabled=prompt_cache_enabled,
            reasoning_enabled=reasoning_enabled,
            reasoning_effort=reasoning_effort,
            stream_enabled=stream_enabled,
            request_params=_get_model_request_params(data, "naga"),
        )

    logger.info(
        "未配置 Naga 审核模型，将使用已解析的安全模型配置作为后备（安全模型本身可能已回退）"
    )
    return SecurityModelConfig(
        api_url=security_model.api_url,
        api_key=security_model.api_key,
        model_name=security_model.model_name,
        use_proxy=use_proxy,
        max_tokens=security_model.max_tokens,
        context_window_tokens=security_model.context_window_tokens,
        queue_interval_seconds=security_model.queue_interval_seconds,
        api_mode=security_model.api_mode,
        thinking_enabled=security_model.thinking_enabled,
        thinking_budget_tokens=security_model.thinking_budget_tokens,
        thinking_include_budget=security_model.thinking_include_budget,
        thinking_tool_call_compat=security_model.thinking_tool_call_compat,
        reasoning_content_replay=security_model.reasoning_content_replay,
        system_prompt_as_user=security_model.system_prompt_as_user,
        responses_tool_choice_compat=security_model.responses_tool_choice_compat,
        responses_force_stateless_replay=security_model.responses_force_stateless_replay,
        prompt_cache_enabled=security_model.prompt_cache_enabled,
        reasoning_enabled=security_model.reasoning_enabled,
        reasoning_effort=security_model.reasoning_effort,
        stream_enabled=security_model.stream_enabled,
        request_params=merge_request_params(security_model.request_params),
    )
