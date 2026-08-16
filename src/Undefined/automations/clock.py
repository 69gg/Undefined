"""Clock-window filters for start / branch.if nodes."""

from __future__ import annotations

from datetime import datetime


def _parse_hhmm(value: str) -> int | None:
    text = str(value or "").strip()
    parts = text.split(":")
    if len(parts) != 2:
        return None
    try:
        hour = int(parts[0])
        minute = int(parts[1])
    except ValueError:
        return None
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        return None
    return hour * 60 + minute


def clock_matches(
    now: datetime,
    *,
    after: str | None = None,
    before: str | None = None,
    weekdays: list[int] | None = None,
) -> bool:
    """Return True when ``now`` is inside the optional clock window.

    ``weekdays`` uses Python's convention: 0=Monday ... 6=Sunday.
    Overnight windows (after > before) wrap past midnight.
    """
    if weekdays:
        allowed = {int(day) for day in weekdays}
        if now.weekday() not in allowed:
            return False
    after_minutes = _parse_hhmm(after) if after else None
    before_minutes = _parse_hhmm(before) if before else None
    current = now.hour * 60 + now.minute
    if after_minutes is not None and before_minutes is not None:
        if after_minutes <= before_minutes:
            return after_minutes <= current < before_minutes
        return current >= after_minutes or current < before_minutes
    if after_minutes is not None:
        return current >= after_minutes
    if before_minutes is not None:
        return current < before_minutes
    return True
