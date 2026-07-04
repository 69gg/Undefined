"""Search tool configuration helpers."""

from __future__ import annotations

from typing import Any, Final

from .coercers import _coerce_str_list

SEARCH_TOOL_GROK: Final = "grok_search"
SEARCH_TOOL_FIRECRAWL: Final = "firecrawl_search"
SEARCH_TOOL_SEARXNG: Final = "web_search"

DEFAULT_SEARCH_PRIORITY: Final[tuple[str, ...]] = (
    SEARCH_TOOL_GROK,
    SEARCH_TOOL_FIRECRAWL,
    SEARCH_TOOL_SEARXNG,
)
KNOWN_SEARCH_TOOLS: Final[frozenset[str]] = frozenset(DEFAULT_SEARCH_PRIORITY)


def normalize_search_priority(value: Any) -> list[str]:
    """Return a stable ordered search tool list from TOML/env input."""

    raw_items = _coerce_str_list(value)
    normalized: list[str] = []
    for item in raw_items:
        if item not in KNOWN_SEARCH_TOOLS or item in normalized:
            continue
        normalized.append(item)

    if not normalized:
        return list(DEFAULT_SEARCH_PRIORITY)

    for item in DEFAULT_SEARCH_PRIORITY:
        if item not in normalized:
            normalized.append(item)
    return normalized
