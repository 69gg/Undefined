from __future__ import annotations

from typing import Any


DEFAULT_QUEUED_LLM_ATTEMPT_TIMEOUT_SECONDS = 480.0
QUEUED_LLM_TIMEOUT_GRACE_SECONDS = 30.0


def _safe_retry_count(runtime_config: Any) -> int:
    try:
        retries = int(getattr(runtime_config, "ai_request_max_retries", 0) or 0)
    except (TypeError, ValueError):
        return 0
    return max(0, retries)


def resolve_effective_retry_count(
    runtime_config: Any, queue_manager: Any = None
) -> int:
    if queue_manager is not None and hasattr(queue_manager, "get_max_retries"):
        try:
            retries = int(queue_manager.get_max_retries())
        except (TypeError, ValueError):
            retries = 0
        return max(0, retries)
    return _safe_retry_count(runtime_config)


def _iter_model_intervals(model_config: Any) -> list[float]:
    intervals: list[float] = []

    def _append_interval(raw: Any) -> None:
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return
        if value >= 0:
            intervals.append(value)

    _append_interval(getattr(model_config, "queue_interval_seconds", 0.0))

    pool = getattr(model_config, "pool", None)
    if pool is not None and bool(getattr(pool, "enabled", False)):
        for entry in list(getattr(pool, "models", []) or []):
            _append_interval(getattr(entry, "queue_interval_seconds", 0.0))

    return intervals


def compute_queued_llm_timeout_seconds(
    runtime_config: Any,
    model_config: Any,
    *,
    retry_count: int | None = None,
    initial_wait_seconds: float = 0.0,
    include_first_dispatch_interval: bool = True,
    attempt_timeout_seconds: float = DEFAULT_QUEUED_LLM_ATTEMPT_TIMEOUT_SECONDS,
    grace_seconds: float = QUEUED_LLM_TIMEOUT_GRACE_SECONDS,
) -> float:
    retries = (
        _safe_retry_count(runtime_config)
        if retry_count is None
        else max(0, retry_count)
    )
    attempts = retries + 1
    max_interval = max(_iter_model_intervals(model_config) or [0.0])
    dispatch_intervals = retries + (1 if include_first_dispatch_interval else 0)
    return (
        initial_wait_seconds
        + (attempt_timeout_seconds * attempts)
        + (max_interval * dispatch_intervals)
        + grace_seconds
    )
