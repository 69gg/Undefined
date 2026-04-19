"""Type-safe coercion helpers shared across the codebase."""

from __future__ import annotations

from typing import Any, overload


@overload
def safe_int(value: Any) -> int | None: ...


@overload
def safe_int(value: Any, default: int) -> int: ...


@overload
def safe_int(value: Any, default: None) -> int | None: ...


def safe_int(value: Any, default: int | None = None) -> int | None:
    """Safely convert *value* to int, returning *default* on failure."""
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def safe_float(value: Any, default: float = 0.0) -> float:
    """Safely convert *value* to float, returning *default* on failure."""
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
