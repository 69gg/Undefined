"""Configuration value resolution helpers."""

from __future__ import annotations

from typing import Any

from .api_modes import API_MODE_OPENAI_CHAT_COMPLETIONS, normalize_api_mode
from .coercers import (
    _coerce_bool,
    _coerce_int,
    _coerce_str,
    _get_value,
)


def _resolve_thinking_compat_flags(
    data: dict[str, Any],
    model_name: str,
    include_budget_env_key: str,
    tool_call_compat_env_key: str,
    legacy_env_key: str,
    *,
    include_budget_default: bool = True,
    tool_call_compat_default: bool = True,
) -> tuple[bool, bool]:
    """解析思维链兼容配置，并兼容旧字段 deepseek_new_cot_support。"""
    include_budget_value = _get_value(
        data,
        ("models", model_name, "thinking_include_budget"),
        include_budget_env_key,
    )
    tool_call_compat_value = _get_value(
        data,
        ("models", model_name, "thinking_tool_call_compat"),
        tool_call_compat_env_key,
    )
    legacy_value = _get_value(
        data,
        ("models", model_name, "deepseek_new_cot_support"),
        legacy_env_key,
    )

    if legacy_value is not None:
        legacy_enabled = _coerce_bool(legacy_value, False)
        include_budget_default = not legacy_enabled
        tool_call_compat_default = legacy_enabled

    return (
        _coerce_bool(include_budget_value, include_budget_default),
        _coerce_bool(tool_call_compat_value, tool_call_compat_default),
    )


def _resolve_api_mode(
    data: dict[str, Any],
    model_name: str,
    env_key: str,
    default: str = API_MODE_OPENAI_CHAT_COMPLETIONS,
) -> str:
    raw_value = _get_value(data, ("models", model_name, "api_mode"), env_key)
    return normalize_api_mode(raw_value, default)


def _resolve_reasoning_effort(value: Any, default: str = "medium") -> str:
    return _coerce_str(value, default).strip()


def _resolve_responses_tool_choice_compat(
    data: dict[str, Any],
    model_name: str,
    env_key: str,
    default: bool = False,
) -> bool:
    return _coerce_bool(
        _get_value(
            data,
            ("models", model_name, "responses_tool_choice_compat"),
            env_key,
        ),
        default,
    )


def _resolve_responses_force_stateless_replay(
    data: dict[str, Any],
    model_name: str,
    env_key: str,
    default: bool = False,
) -> bool:
    return _coerce_bool(
        _get_value(
            data,
            ("models", model_name, "responses_force_stateless_replay"),
            env_key,
        ),
        default,
    )


def _resolve_reasoning_content_replay(
    data: dict[str, Any],
    model_name: str,
    env_key: str,
    *,
    default: bool = True,
) -> bool:
    return _coerce_bool(
        _get_value(
            data,
            ("models", model_name, "reasoning_content_replay"),
            env_key,
        ),
        default,
    )


def _resolve_system_prompt_as_user(
    data: dict[str, Any],
    model_name: str,
    env_key: str,
    *,
    default: bool = False,
) -> bool:
    return _coerce_bool(
        _get_value(
            data,
            ("models", model_name, "system_prompt_as_user"),
            env_key,
        ),
        default,
    )


def _resolve_context_window_tokens(
    data: dict[str, Any],
    model_name: str,
    env_key: str,
    *,
    default: int = 8192,
) -> int:
    return max(
        1,
        _coerce_int(
            _get_value(
                data,
                ("models", model_name, "context_window_tokens"),
                env_key,
            ),
            default,
        ),
    )
