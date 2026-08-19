"""Build APScheduler triggers from start nodes."""

from __future__ import annotations

from datetime import datetime
import re
from typing import Any

from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

from Undefined.automations.runner import find_start_node

_WEEKDAY_NAMES = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
_HHMM_PATTERN = re.compile(r"\d{2}:\d{2}\Z")


def parse_cron_expression(value: str) -> CronTrigger:
    """Parse a five-field crontab expression using APScheduler's rules."""
    expression = str(value).strip()
    if not expression:
        raise ValueError("cron expression is required")
    return CronTrigger.from_crontab(expression)


def parse_daily_time(value: str) -> tuple[int, int]:
    """Parse a zero-padded HH:MM wall-clock time."""
    raw = str(value).strip()
    if _HHMM_PATTERN.fullmatch(raw) is None:
        raise ValueError("time must be HH:MM")
    hour, minute = (int(part) for part in raw.split(":"))
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        raise ValueError("time must be HH:MM")
    return hour, minute


def parse_at_datetime(value: str) -> datetime:
    """Parse an ISO-8601 datetime containing both a date and a time."""
    raw = str(value).strip()
    if "T" not in raw and " " not in raw:
        raise ValueError("at must be an ISO-8601 datetime")
    try:
        return datetime.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError("at must be an ISO-8601 datetime") from exc


def build_apscheduler_trigger(task: dict[str, Any]) -> Any | None:
    """Return an APScheduler trigger for time-based starts, else None."""
    start = find_start_node(task)
    if start is None:
        cron = str(task.get("cron") or "").strip()
        if cron:
            return parse_cron_expression(cron)
        return None
    kind = str(start.get("kind") or "").strip()
    if kind == "cron":
        cron = str(start.get("cron") or task.get("cron") or "").strip()
        if not cron:
            return None
        return parse_cron_expression(cron)
    if kind == "daily":
        hour, minute = parse_daily_time(str(start.get("time") or ""))
        weekdays = start.get("weekdays")
        kwargs: dict[str, Any] = {"hour": hour, "minute": minute}
        if isinstance(weekdays, list) and weekdays:
            names = []
            for item in weekdays:
                try:
                    index = int(item)
                except (TypeError, ValueError):
                    continue
                if 0 <= index <= 6:
                    names.append(_WEEKDAY_NAMES[index])
            if names:
                kwargs["day_of_week"] = ",".join(names)
        return CronTrigger(**kwargs)
    if kind == "at":
        raw = str(start.get("at") or "").strip()
        when = parse_at_datetime(raw)
        return DateTrigger(run_date=when)
    if kind == "interval":
        seconds = int(start.get("interval_seconds") or 0)
        if seconds < 1:
            return None
        return IntervalTrigger(seconds=seconds)
    return None
