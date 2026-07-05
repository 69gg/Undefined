"""Historian model parser."""

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
    _get_value,
    _normalize_queue_interval,
)
from ..models import (
    AgentModelConfig,
)
from ..resolvers import (
    _resolve_api_mode,
    _resolve_reasoning_effort,
    _resolve_reasoning_effort_style,
    _resolve_responses_force_stateless_replay,
    _resolve_responses_tool_choice_compat,
    _resolve_thinking_compat_flags,
)

logger = logging.getLogger(__name__)


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
    context_window_tokens = _coerce_int(
        h.get("context_window_tokens"), fallback.context_window_tokens
    )
    return AgentModelConfig(
        api_url=_coerce_str(h.get("api_url"), fallback.api_url),
        api_key=_coerce_str(h.get("api_key"), fallback.api_key),
        model_name=_coerce_str(h.get("model_name"), fallback.model_name),
        max_tokens=_coerce_int(h.get("max_tokens"), fallback.max_tokens),
        context_window_tokens=context_window_tokens,
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
        reasoning_content_replay=_coerce_bool(
            h.get("reasoning_content_replay"), fallback.reasoning_content_replay
        ),
        system_prompt_as_user=_coerce_bool(
            h.get("system_prompt_as_user"), fallback.system_prompt_as_user
        ),
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
        stream_enabled=_coerce_bool(
            _get_value(
                {"models": {"historian": h}},
                ("models", "historian", "stream_enabled"),
                "HISTORIAN_MODEL_STREAM_ENABLED",
            ),
            fallback.stream_enabled,
        ),
        use_proxy=_coerce_bool(
            _get_value(
                {"models": {"historian": h}},
                ("models", "historian", "use_proxy"),
                "HISTORIAN_MODEL_USE_PROXY",
            ),
            False,
        ),
        request_params=merge_request_params(
            fallback.request_params,
            h.get("request_params"),
        ),
    )
