"""Configuration value resolution helpers."""

from __future__ import annotations

from typing import Any

from .coercers import (
    _coerce_bool,
    _coerce_str,
    _get_value,
    _VALID_API_MODES,
    _VALID_REASONING_EFFORT_STYLES,
)


def _resolve_reasoning_effort_style(value: Any, default: str = "openai") -> str:
    style = _coerce_str(value, default).strip().lower()
    if style not in _VALID_REASONING_EFFORT_STYLES:
        return default
    return style


def _resolve_thinking_compat_flags(
    data: dict[str, Any],
    model_name: str,
    include_budget_env_key: str,
    tool_call_compat_env_key: str,
    legacy_env_key: str,
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

    include_budget_default = True
    tool_call_compat_default = True
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
    default: str = "chat_completions",
) -> str:
    raw_value = _get_value(data, ("models", model_name, "api_mode"), env_key)
    value = _coerce_str(raw_value, default).strip().lower()
    if value not in _VALID_API_MODES:
        return default
    return value


def _resolve_reasoning_effort(value: Any, default: str = "medium") -> str:
    return _coerce_str(value, default).strip().lower()


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
