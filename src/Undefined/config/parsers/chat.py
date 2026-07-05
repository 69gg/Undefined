"""Chat model parser."""

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
    ChatModelConfig,
)
from ..resolvers import (
    _resolve_api_mode,
    _resolve_context_window_tokens,
    _resolve_reasoning_effort,
    _resolve_reasoning_effort_style,
    _resolve_reasoning_content_replay,
    _resolve_responses_force_stateless_replay,
    _resolve_responses_tool_choice_compat,
    _resolve_system_prompt_as_user,
    _resolve_thinking_compat_flags,
)
from .pool import _parse_model_pool

logger = logging.getLogger(__name__)


# 解析 [models.chat]：主对话模型 API、thinking/reasoning、队列间隔与模型池
def _parse_chat_model_config(data: dict[str, Any]) -> ChatModelConfig:
    # 该模型独立的发车间隔（秒），0=立即发车
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
    # DeepSeek/兼容模型的 thinking 预算与 tool_call 互斥开关
    thinking_include_budget, thinking_tool_call_compat = _resolve_thinking_compat_flags(
        data=data,
        model_name="chat",
        include_budget_env_key="CHAT_MODEL_THINKING_INCLUDE_BUDGET",
        tool_call_compat_env_key="CHAT_MODEL_THINKING_TOOL_CALL_COMPAT",
        legacy_env_key="CHAT_MODEL_DEEPSEEK_NEW_COT_SUPPORT",
    )
    # OpenAI 兼容层：chat_completions / responses 及 reasoning 回放策略
    api_mode = _resolve_api_mode(data, "chat", "CHAT_MODEL_API_MODE")
    responses_tool_choice_compat = _resolve_responses_tool_choice_compat(
        data, "chat", "CHAT_MODEL_RESPONSES_TOOL_CHOICE_COMPAT"
    )
    responses_force_stateless_replay = _resolve_responses_force_stateless_replay(
        data, "chat", "CHAT_MODEL_RESPONSES_FORCE_STATELESS_REPLAY"
    )
    reasoning_content_replay = _resolve_reasoning_content_replay(
        data, "chat", "CHAT_MODEL_REASONING_CONTENT_REPLAY"
    )
    system_prompt_as_user = _resolve_system_prompt_as_user(
        data, "chat", "CHAT_MODEL_SYSTEM_PROMPT_AS_USER"
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
    stream_enabled = _coerce_bool(
        _get_value(
            data,
            ("models", "chat", "stream_enabled"),
            "CHAT_MODEL_STREAM_ENABLED",
        ),
        False,
    )
    context_window_tokens = _resolve_context_window_tokens(
        data, "chat", "CHAT_MODEL_CONTEXT_WINDOW_TOKENS"
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
        use_proxy=_coerce_bool(
            _get_value(data, ("models", "chat", "use_proxy"), "CHAT_MODEL_USE_PROXY"),
            False,
        ),
        context_window_tokens=context_window_tokens,
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
        reasoning_content_replay=reasoning_content_replay,
        system_prompt_as_user=system_prompt_as_user,
        responses_tool_choice_compat=responses_tool_choice_compat,
        responses_force_stateless_replay=responses_force_stateless_replay,
        prompt_cache_enabled=prompt_cache_enabled,
        reasoning_enabled=reasoning_enabled,
        reasoning_effort=reasoning_effort,
        stream_enabled=stream_enabled,
        request_params=_get_model_request_params(data, "chat"),
    )
    config.pool = _parse_model_pool(data, "chat", config)
    return config
