from __future__ import annotations

from typing import Any

import pytest

from Undefined.cognitive.vector_store_compat import call_vector_store_method


@pytest.mark.asyncio
async def test_call_vector_store_method_omits_priority_for_legacy_method() -> None:
    calls: list[dict[str, Any]] = []

    async def _legacy_method(value: str, *, top_k: int) -> str:
        calls.append({"value": value, "top_k": top_k})
        return "ok"

    result = await call_vector_store_method(
        _legacy_method,
        "query",
        priority="foreground",
        top_k=3,
    )

    assert result == "ok"
    assert calls == [{"value": "query", "top_k": 3}]


@pytest.mark.asyncio
async def test_call_vector_store_method_passes_priority_when_supported() -> None:
    calls: list[dict[str, Any]] = []

    async def _new_method(value: str, *, top_k: int, priority: str) -> str:
        calls.append({"value": value, "top_k": top_k, "priority": priority})
        return "ok"

    result = await call_vector_store_method(
        _new_method,
        "query",
        priority="foreground_critical",
        top_k=3,
    )

    assert result == "ok"
    assert calls == [{"value": "query", "top_k": 3, "priority": "foreground_critical"}]
