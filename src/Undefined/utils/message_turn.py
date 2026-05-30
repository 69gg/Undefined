"""Helpers for tracking per-turn user-visible output."""

from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any

from Undefined.context import RequestContext


def mark_message_sent_this_turn(
    context: MutableMapping[str, Any] | None = None,
) -> None:
    """Mark the current turn as having produced user-visible output.

    Tool runners may execute tools with copied context dictionaries. Writing
    the flag to both the passed context and the active request context keeps
    downstream tools such as ``end`` from missing a successful send.
    """
    if context is not None:
        context["message_sent_this_turn"] = True
    request_context = RequestContext.current()
    if request_context is not None:
        request_context.set_resource("message_sent_this_turn", True)
