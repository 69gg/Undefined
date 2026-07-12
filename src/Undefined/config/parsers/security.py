"""Security model parser."""

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
    ChatModelConfig,
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
    reasoning_content_replay = _resolve_reasoning_content_replay(
        data, "security", "SECURITY_MODEL_REASONING_CONTENT_REPLAY"
    )
    system_prompt_as_user = _resolve_system_prompt_as_user(
        data, "security", "SECURITY_MODEL_SYSTEM_PROMPT_AS_USER"
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
    stream_enabled = _coerce_bool(
        _get_value(
            data,
            ("models", "security", "stream_enabled"),
            "SECURITY_MODEL_STREAM_ENABLED",
        ),
        False,
    )
    use_proxy = _coerce_bool(
        _get_value(
            data, ("models", "security", "use_proxy"), "SECURITY_MODEL_USE_PROXY"
        ),
        False,
    )

    context_window_tokens = _resolve_context_window_tokens(
        data, "security", "SECURITY_MODEL_CONTEXT_WINDOW_TOKENS"
    )
    if api_url and api_key and model_name:
        return SecurityModelConfig(
            api_url=api_url,
            api_key=api_key,
            model_name=model_name,
            use_proxy=use_proxy,
            max_tokens=_coerce_int(
                _get_value(
                    data,
                    ("models", "security", "max_tokens"),
                    "SECURITY_MODEL_MAX_TOKENS",
                ),
                100,
            ),
            context_window_tokens=context_window_tokens,
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
            thinking_tool_call_compat=thinking_tool_call_compat,
            reasoning_content_replay=reasoning_content_replay,
            system_prompt_as_user=system_prompt_as_user,
            responses_tool_choice_compat=responses_tool_choice_compat,
            responses_force_stateless_replay=responses_force_stateless_replay,
            prompt_cache_enabled=prompt_cache_enabled,
            reasoning_enabled=reasoning_enabled,
            reasoning_effort=reasoning_effort,
            stream_enabled=stream_enabled,
            request_params=_get_model_request_params(data, "security"),
        )

    logger.warning("未配置安全模型，将使用对话模型作为后备")
    return SecurityModelConfig(
        api_url=chat_model.api_url,
        api_key=chat_model.api_key,
        model_name=chat_model.model_name,
        use_proxy=use_proxy,
        context_window_tokens=chat_model.context_window_tokens,
        max_tokens=chat_model.max_tokens,
        queue_interval_seconds=chat_model.queue_interval_seconds,
        api_mode=chat_model.api_mode,
        thinking_enabled=False,
        thinking_budget_tokens=0,
        thinking_include_budget=True,
        thinking_tool_call_compat=chat_model.thinking_tool_call_compat,
        reasoning_content_replay=chat_model.reasoning_content_replay,
        system_prompt_as_user=chat_model.system_prompt_as_user,
        responses_tool_choice_compat=chat_model.responses_tool_choice_compat,
        responses_force_stateless_replay=chat_model.responses_force_stateless_replay,
        prompt_cache_enabled=chat_model.prompt_cache_enabled,
        reasoning_enabled=chat_model.reasoning_enabled,
        reasoning_effort=chat_model.reasoning_effort,
        stream_enabled=chat_model.stream_enabled,
        request_params=merge_request_params(chat_model.request_params),
    )
