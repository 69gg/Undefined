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


def copy_transport_message_metadata(
    source: dict[str, Any],
    target: dict[str, Any],
    *,
    include_readable_reasoning: bool,
) -> None:
    """Copy raw replay structures, plus legacy readable reasoning when enabled."""
    for key in _TRANSPORT_MESSAGE_METADATA_KEYS:
        if key in source:
            target[key] = deepcopy(source[key])
    if include_readable_reasoning and source.get("reasoning_content") is not None:
        target["reasoning_content"] = deepcopy(source["reasoning_content"])


__all__ = ["copy_transport_message_metadata"]
