"""Canonical LLM API mode names and compatibility aliases."""

from __future__ import annotations

import logging
from typing import Any, Final

logger = logging.getLogger(__name__)

API_MODE_OPENAI_CHAT_COMPLETIONS: Final = "openai.chat_completions"
API_MODE_OPENAI_RESPONSES: Final = "openai.responses"
API_MODE_ANTHROPIC_MESSAGES: Final = "anthropic.messages"

VALID_API_MODES: Final[frozenset[str]] = frozenset(
    {
        API_MODE_OPENAI_CHAT_COMPLETIONS,
        API_MODE_OPENAI_RESPONSES,
        API_MODE_ANTHROPIC_MESSAGES,
    }
)

LEGACY_API_MODE_ALIASES: Final[dict[str, str]] = {
    "chat_completions": API_MODE_OPENAI_CHAT_COMPLETIONS,
    "responses": API_MODE_OPENAI_RESPONSES,
}

_WARNED_LEGACY_API_MODES: set[str] = set()


def normalize_api_mode(
    value: Any,
    default: str = API_MODE_OPENAI_CHAT_COMPLETIONS,
    *,
    warn_legacy: bool = True,
) -> str:
    """Normalize canonical modes while accepting legacy OpenAI aliases."""
    normalized_default = LEGACY_API_MODE_ALIASES.get(default, default)
    if normalized_default not in VALID_API_MODES:
        normalized_default = API_MODE_OPENAI_CHAT_COMPLETIONS

    text = str(value or normalized_default).strip().lower()
    canonical = LEGACY_API_MODE_ALIASES.get(text, text)
    if text in LEGACY_API_MODE_ALIASES and warn_legacy:
        if text not in _WARNED_LEGACY_API_MODES:
            _WARNED_LEGACY_API_MODES.add(text)
            logger.warning(
                "[配置弃用] api_mode=%s 已弃用，请改为 api_mode=%s",
                text,
                canonical,
            )
    return canonical if canonical in VALID_API_MODES else normalized_default


__all__ = [
    "API_MODE_ANTHROPIC_MESSAGES",
    "API_MODE_OPENAI_CHAT_COMPLETIONS",
    "API_MODE_OPENAI_RESPONSES",
    "LEGACY_API_MODE_ALIASES",
    "VALID_API_MODES",
    "normalize_api_mode",
]
