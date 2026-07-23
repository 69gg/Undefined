"""Model pool parser."""

from __future__ import annotations

# 模型配置解析：原始 dict → ChatModelConfig 等 dataclass

import logging
from typing import Any

from Undefined.utils.request_params import merge_request_params

from ..api_modes import normalize_api_mode
from ..coercers import (
    _coerce_bool,
    _coerce_float,
    _coerce_int,
    _coerce_str,
    _normalize_queue_interval,
)
from ..models import AgentModelConfig, ChatModelConfig, ModelPool, ModelPoolEntry
from ..resolvers import _resolve_reasoning_effort

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
                use_proxy=_coerce_bool(item.get("use_proxy"), False),
                context_window_tokens=_coerce_int(
                    item.get("context_window_tokens"),
                    primary_config.context_window_tokens,
                ),
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
                api_mode=normalize_api_mode(
                    item.get("api_mode"),
                    primary_config.api_mode,
                ),
                thinking_enabled=_coerce_bool(
                    item.get("thinking_enabled"), primary_config.thinking_enabled
                ),
                thinking_param_enabled=_coerce_bool(
                    item.get("thinking_param_enabled"),
                    primary_config.thinking_param_enabled,
                ),
                thinking_budget_tokens=_coerce_int(
                    item.get("thinking_budget_tokens"),
                    primary_config.thinking_budget_tokens,
                ),
                thinking_include_budget=_coerce_bool(
                    item.get("thinking_include_budget"),
                    primary_config.thinking_include_budget,
                ),
                thinking_tool_call_compat=_coerce_bool(
                    item.get("thinking_tool_call_compat"),
                    primary_config.thinking_tool_call_compat,
                ),
                reasoning_content_replay=_coerce_bool(
                    item.get("reasoning_content_replay"),
                    primary_config.reasoning_content_replay,
                ),
                system_prompt_as_user=_coerce_bool(
                    item.get("system_prompt_as_user"),
                    primary_config.system_prompt_as_user,
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
                stream_enabled=_coerce_bool(
                    item.get("stream_enabled"),
                    getattr(primary_config, "stream_enabled", False),
                ),
                request_params=merge_request_params(
                    primary_config.request_params,
                    item.get("request_params"),
                ),
            )
        )

    return ModelPool(enabled=enabled, strategy=strategy, models=entries)
