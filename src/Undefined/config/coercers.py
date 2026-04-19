"""Type coercion and normalization helpers for config loading."""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

from Undefined.utils.request_params import normalize_request_params

logger = logging.getLogger(__name__)

_ENV_WARNED_KEYS: set[str] = set()


def _warn_env_fallback(name: str) -> None:
    if name in _ENV_WARNED_KEYS:
        return
    _ENV_WARNED_KEYS.add(name)
    logger.warning("检测到环境变量 %s，建议迁移到 config.toml", name)


def _get_nested(data: dict[str, Any], path: tuple[str, ...]) -> Any:
    node: Any = data
    for key in path:
        if not isinstance(node, dict) or key not in node:
            return None
        node = node[key]
    return node


def _normalize_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped if stripped else None
    return str(value).strip()


def _coerce_int(value: Any, default: int) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _coerce_float(value: Any, default: float) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalize_queue_interval(value: float, default: float = 1.0) -> float:
    """规范化队列发车间隔。

    `0` 表示立即发车，负数回退到默认值。
    """

    return default if value < 0 else value


def _coerce_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return default


def _coerce_str(value: Any, default: str) -> str:
    normalized = _normalize_str(value)
    return normalized if normalized is not None else default


def _normalize_base_url(value: str, default: str) -> str:
    normalized = value.strip().rstrip("/")
    if normalized:
        return normalized
    return default.rstrip("/")


def _coerce_int_list(value: Any) -> list[int]:
    if value is None:
        return []
    if isinstance(value, list):
        items: list[int] = []
        for item in value:
            try:
                items.append(int(item))
            except (TypeError, ValueError):
                continue
        return items
    if isinstance(value, str):
        parts = [part.strip() for part in value.split(",") if part.strip()]
        items = []
        for part in parts:
            try:
                items.append(int(part))
            except ValueError:
                continue
        return items
    return []


def _coerce_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    return []


def _coerce_request_params(value: Any) -> dict[str, Any]:
    return normalize_request_params(value)


def _get_model_request_params(data: dict[str, Any], model_name: str) -> dict[str, Any]:
    return _coerce_request_params(
        _get_nested(data, ("models", model_name, "request_params"))
    )


def _get_value(
    data: dict[str, Any],
    path: tuple[str, ...],
    env_key: Optional[str],
) -> Any:
    value = _get_nested(data, path)
    if value is not None:
        return value
    if env_key:
        env_value = os.getenv(env_key)
        if env_value is not None and str(env_value).strip() != "":
            _warn_env_fallback(env_key)
            return env_value
    return None


_VALID_API_MODES = {"chat_completions", "responses"}
_VALID_REASONING_EFFORT_STYLES = {"openai", "anthropic"}
