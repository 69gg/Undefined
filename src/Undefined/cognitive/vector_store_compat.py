"""Compatibility helpers for cognitive vector store calls."""

from __future__ import annotations

import inspect
from typing import Any


def _accepts_keyword(method: Any, keyword: str) -> bool:
    try:
        signature = inspect.signature(method)
    except (TypeError, ValueError):
        return True
    for parameter in signature.parameters.values():
        if parameter.kind is inspect.Parameter.VAR_KEYWORD:
            return True
        if parameter.name == keyword and parameter.kind in {
            inspect.Parameter.KEYWORD_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        }:
            return True
    return False


async def call_vector_store_method(
    method: Any,
    *args: Any,
    priority: str,
    **kwargs: Any,
) -> Any:
    """Call a vector-store method with priority when the method supports it."""
    call_kwargs = dict(kwargs)
    if _accepts_keyword(method, "priority"):
        call_kwargs["priority"] = priority
    result = method(*args, **call_kwargs)
    if inspect.isawaitable(result):
        return await result
    return result
