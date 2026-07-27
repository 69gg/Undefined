"""Helpers for preserving lossless transport metadata in local history."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .anthropic_transport import ANTHROPIC_CONTENT_BLOCKS_KEY
from .openai_transport import (
    CHAT_REASONING_REPLAY_KEY,
    RESPONSES_OUTPUT_ITEMS_KEY,
    RESPONSES_REASONING_REPLAY_KEY,
)

_TRANSPORT_MESSAGE_METADATA_KEYS: tuple[str, ...] = (
    CHAT_REASONING_REPLAY_KEY,
    RESPONSES_REASONING_REPLAY_KEY,
    RESPONSES_OUTPUT_ITEMS_KEY,
    ANTHROPIC_CONTENT_BLOCKS_KEY,
)


def _strip_recovered_text_content(key: str, value: Any) -> Any:
    """Remove the raw text envelope while preserving native reasoning items."""

    if not isinstance(value, list):
        return deepcopy(value)
    if key == ANTHROPIC_CONTENT_BLOCKS_KEY:
        return [
            deepcopy(block)
            for block in value
            if not isinstance(block, dict)
            or str(block.get("type") or "").strip().lower() != "text"
        ]
    if key == RESPONSES_OUTPUT_ITEMS_KEY:
        return [
            deepcopy(item)
            for item in value
            if not isinstance(item, dict)
            or str(item.get("type") or "").strip().lower()
            not in {"message", "text", "output_text"}
        ]
    return deepcopy(value)


def copy_transport_message_metadata(
    source: dict[str, Any],
    target: dict[str, Any],
    *,
    include_readable_reasoning: bool,
    strip_text_content_blocks: bool = False,
) -> None:
    """Copy raw replay structures, plus legacy readable reasoning when enabled."""
    for key in _TRANSPORT_MESSAGE_METADATA_KEYS:
        if key in source:
            value = source[key]
            target[key] = (
                _strip_recovered_text_content(key, value)
                if strip_text_content_blocks
                else deepcopy(value)
            )
    if include_readable_reasoning and source.get("reasoning_content") is not None:
        target["reasoning_content"] = deepcopy(source["reasoning_content"])


__all__ = ["copy_transport_message_metadata"]
