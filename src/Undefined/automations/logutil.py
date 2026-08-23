"""Shared log formatting for the automation runtime."""

from __future__ import annotations


def preview_text(value: object, *, limit: int = 80) -> str:
    """Collapse whitespace and truncate a value for log lines."""
    text = (
        str(value if value is not None else "").replace("\r", "").replace("\n", "\\n")
    )
    if len(text) <= limit:
        return text
    return f"{text[:limit]}…(len={len(text)})"
