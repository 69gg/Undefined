"""Grok model parser."""

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
    GrokModelConfig,
)
from ..resolvers import (
    _resolve_context_window_tokens,
    _resolve_reasoning_effort,
    _resolve_reasoning_effort_style,
)

logger = logging.getLogger(__name__)


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
    context_window_tokens = _resolve_context_window_tokens(
        data, "grok", "GROK_MODEL_CONTEXT_WINDOW_TOKENS"
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
        context_window_tokens=context_window_tokens,
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
        stream_enabled=_coerce_bool(
            _get_value(
                data,
                ("models", "grok", "stream_enabled"),
                "GROK_MODEL_STREAM_ENABLED",
            ),
            False,
        ),
        use_proxy=_coerce_bool(
            _get_value(data, ("models", "grok", "use_proxy"), "GROK_MODEL_USE_PROXY"),
            False,
        ),
        request_params=_get_model_request_params(data, "grok"),
    )
