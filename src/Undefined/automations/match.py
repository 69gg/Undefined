"""Start / branch.if condition matching against inbound events."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from Undefined.automations.clock import clock_matches
from Undefined.automations.constants import (
    DEFAULT_REGEX_TIMEOUT_SECONDS,
    EVENT_KINDS,
    TEXT_MATCH_MODES,
    TIME_KINDS,
)
from Undefined.automations.mentions import MentionConsumeResult, consume_mentions

logger = logging.getLogger(__name__)


@dataclass
class AutomationEvent:
    """Normalized inbound event for automation matching."""

    kind: str
    channel: str
    text: str = ""
    sender_id: int | None = None
    nickname: str = ""
    group_id: int | None = None
    user_id: int | None = None
    address: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class StartMatch:
    """Successful start-node match, including stripped trigger text."""

    consume_result: MentionConsumeResult
    pass_text: str


def _as_int_list(value: Any) -> list[int]:
    result: list[int] = []
    if not isinstance(value, list):
        return result
    for item in value:
        try:
            result.append(int(item))
        except (TypeError, ValueError):
            continue
    return result


def _as_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def match_text(text: str, pattern: str, mode: str) -> bool:
    """Match remaining text after mention stripping."""
    needle = str(pattern or "")
    if not needle:
        return True
    haystack = str(text or "")
    normalized_mode = mode if mode in TEXT_MATCH_MODES else "contains"
    if normalized_mode == "contains":
        return needle in haystack
    if normalized_mode == "keyword":
        words = [part for part in needle.split() if part]
        return all(word in haystack for word in words)
    return _regex_search(needle, haystack)


def _regex_search(
    pattern: str, haystack: str, timeout: float = DEFAULT_REGEX_TIMEOUT_SECONDS
) -> bool:
    """Search with length caps and a wall-clock timeout to limit ReDoS."""
    _ = timeout
    if len(pattern) > 256 or len(haystack) > 20_000:
        logger.warning("[自动化] 正则过长，已拒绝")
        return False
    try:
        compiled = re.compile(pattern)
    except re.error:
        logger.warning("[自动化] 无效正则: %s", pattern)
        return False
    try:
        return compiled.search(haystack) is not None
    except Exception:
        logger.warning("[自动化] 正则匹配失败: %s", pattern)
        return False


def _clock_from_node(node: dict[str, Any]) -> dict[str, Any]:
    raw = node.get("clock")
    if isinstance(raw, dict):
        return raw
    return {}


def match_condition_on_text(
    text: str,
    condition: dict[str, Any],
    *,
    now: datetime | None = None,
    sender_id: int | None = None,
) -> MentionConsumeResult | None:
    """Apply mention + remaining-text + clock + sender filters to a string."""
    mentions = _as_str_list(condition.get("mentions"))
    consume = consume_mentions(text, mentions)
    if not consume.matched:
        return None
    if not match_text(
        consume.stripped,
        str(condition.get("text") or ""),
        str(condition.get("text_match") or "contains"),
    ):
        return None
    sender_ids = _as_int_list(condition.get("sender_ids") or condition.get("user_ids"))
    if sender_ids and (sender_id is None or int(sender_id) not in sender_ids):
        return None
    clock = _clock_from_node(condition)
    if clock and not clock_matches(
        now or datetime.now(),
        after=str(clock.get("after") or "") or None,
        before=str(clock.get("before") or "") or None,
        weekdays=_as_int_list(clock.get("weekdays")) or None,
    ):
        return None
    return consume


def match_start_node(
    start: dict[str, Any],
    event: AutomationEvent,
    *,
    now: datetime | None = None,
) -> StartMatch | None:
    """Return a StartMatch when the start node accepts this event."""
    kind = str(start.get("kind") or "").strip()
    if event.kind == "time":
        if kind not in TIME_KINDS:
            return None
        consume = consume_mentions(event.text, [])
        return StartMatch(consume_result=consume, pass_text=event.text)

    if kind not in EVENT_KINDS or kind != event.kind:
        return None

    channels = _as_str_list(start.get("channels"))
    if not channels:
        return None
    if event.channel not in channels:
        return None

    if event.channel == "group":
        group_ids = _as_int_list(start.get("group_ids"))
        if group_ids and (
            event.group_id is None or int(event.group_id) not in group_ids
        ):
            return None

    user_ids = _as_int_list(start.get("user_ids"))
    if user_ids:
        candidate = event.sender_id if event.channel == "group" else event.user_id
        if candidate is None:
            candidate = event.sender_id
        if candidate is None or int(candidate) not in user_ids:
            return None

    consume_result = match_condition_on_text(
        event.text,
        start,
        now=now,
        sender_id=event.sender_id,
    )
    if consume_result is None:
        return None

    pass_mode = str(start.get("pass_text") or "").strip()
    if not pass_mode:
        pass_mode = "stripped" if _as_str_list(start.get("mentions")) else "original"
    pass_text = event.text if pass_mode == "original" else consume_result.stripped
    return StartMatch(consume_result=consume_result, pass_text=pass_text)
