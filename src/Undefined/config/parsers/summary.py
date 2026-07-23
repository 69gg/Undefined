"""Summary model parser."""

from __future__ import annotations

# 模型配置解析：原始 dict → ChatModelConfig 等 dataclass

import logging
from dataclasses import replace
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
    _resolve_reasoning_content_replay,
    _resolve_reasoning_effort,
    _resolve_responses_force_stateless_replay,
    _resolve_responses_tool_choice_compat,
    _resolve_system_prompt_as_user,
    _resolve_thinking_compat_flags,
    _resolve_thinking_param_enabled,
)

logger = logging.getLogger(__name__)


def _parse_summary_model_config(
    data: dict[str, Any], fallback: AgentModelConfig
) -> tuple[AgentModelConfig, bool]:
    s = data.get("models", {}).get("summary", {})
    thinking_param_enabled = _resolve_thinking_param_enabled(
        data,
        "summary",
        "SUMMARY_MODEL_THINKING_PARAM_ENABLED",
        default=fallback.thinking_param_enabled,
    )
    if not isinstance(s, dict) or not s:
        if thinking_param_enabled == fallback.thinking_param_enabled:
            return fallback, False
        return replace(fallback, thinking_param_enabled=thinking_param_enabled), False
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
        include_budget_default=fallback.thinking_include_budget,
        tool_call_compat_default=fallback.thinking_tool_call_compat,
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
    reasoning_content_replay = _resolve_reasoning_content_replay(
        {"models": {"summary": s}},
        "summary",
        "SUMMARY_MODEL_REASONING_CONTENT_REPLAY",
        default=fallback.reasoning_content_replay,
    )
    system_prompt_as_user = _resolve_system_prompt_as_user(
        {"models": {"summary": s}},
        "summary",
        "SUMMARY_MODEL_SYSTEM_PROMPT_AS_USER",
        default=fallback.system_prompt_as_user,
    )
    prompt_cache_enabled = _coerce_bool(
        _get_value(
            {"models": {"summary": s}},
            ("models", "summary", "prompt_cache_enabled"),
            "SUMMARY_MODEL_PROMPT_CACHE_ENABLED",
        ),
        fallback.prompt_cache_enabled,
    )
    context_window_tokens = _coerce_int(
        s.get("context_window_tokens"), fallback.context_window_tokens
    )
    return (
        AgentModelConfig(
            api_url=_coerce_str(s.get("api_url"), fallback.api_url),
            api_key=_coerce_str(s.get("api_key"), fallback.api_key),
            model_name=_coerce_str(s.get("model_name"), fallback.model_name),
            max_tokens=_coerce_int(s.get("max_tokens"), fallback.max_tokens),
            context_window_tokens=context_window_tokens,
            queue_interval_seconds=queue_interval_seconds,
            api_mode=api_mode,
            thinking_param_enabled=thinking_param_enabled,
            thinking_enabled=_coerce_bool(
                s.get("thinking_enabled"), fallback.thinking_enabled
            ),
            thinking_budget_tokens=_coerce_int(
                s.get("thinking_budget_tokens"), fallback.thinking_budget_tokens
            ),
            thinking_include_budget=thinking_include_budget,
            thinking_tool_call_compat=thinking_tool_call_compat,
            reasoning_content_replay=reasoning_content_replay,
            system_prompt_as_user=system_prompt_as_user,
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
            stream_enabled=_coerce_bool(
                _get_value(
                    {"models": {"summary": s}},
                    ("models", "summary", "stream_enabled"),
                    "SUMMARY_MODEL_STREAM_ENABLED",
                ),
                fallback.stream_enabled,
            ),
            use_proxy=_coerce_bool(
                _get_value(
                    {"models": {"summary": s}},
                    ("models", "summary", "use_proxy"),
                    "SUMMARY_MODEL_USE_PROXY",
                ),
                False,
            ),
            request_params=merge_request_params(
                fallback.request_params,
                s.get("request_params"),
            ),
        ),
        True,
    )
