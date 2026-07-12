"""Agent model parser."""

from __future__ import annotations

# 模型配置解析：原始 dict → ChatModelConfig 等 dataclass

import logging
from typing import Any


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
    AgentModelConfig,
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
from .pool import _parse_model_pool

logger = logging.getLogger(__name__)


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
    reasoning_content_replay = _resolve_reasoning_content_replay(
        data, "agent", "AGENT_MODEL_REASONING_CONTENT_REPLAY"
    )
    system_prompt_as_user = _resolve_system_prompt_as_user(
        data, "agent", "AGENT_MODEL_SYSTEM_PROMPT_AS_USER"
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
    stream_enabled = _coerce_bool(
        _get_value(
            data,
            ("models", "agent", "stream_enabled"),
            "AGENT_MODEL_STREAM_ENABLED",
        ),
        False,
    )
    context_window_tokens = _resolve_context_window_tokens(
        data, "agent", "AGENT_MODEL_CONTEXT_WINDOW_TOKENS"
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
        use_proxy=_coerce_bool(
            _get_value(data, ("models", "agent", "use_proxy"), "AGENT_MODEL_USE_PROXY"),
            False,
        ),
        max_tokens=_coerce_int(
            _get_value(
                data, ("models", "agent", "max_tokens"), "AGENT_MODEL_MAX_TOKENS"
            ),
            4096,
        ),
        context_window_tokens=context_window_tokens,
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
        thinking_tool_call_compat=thinking_tool_call_compat,
        reasoning_content_replay=reasoning_content_replay,
        system_prompt_as_user=system_prompt_as_user,
        responses_tool_choice_compat=responses_tool_choice_compat,
        responses_force_stateless_replay=responses_force_stateless_replay,
        prompt_cache_enabled=prompt_cache_enabled,
        reasoning_enabled=reasoning_enabled,
        reasoning_effort=reasoning_effort,
        stream_enabled=stream_enabled,
        request_params=_get_model_request_params(data, "agent"),
    )
    config.pool = _parse_model_pool(data, "agent", config)
    return config
