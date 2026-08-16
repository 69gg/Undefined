"""Build APScheduler triggers from start nodes."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

from Undefined.automations.runner import find_start_node

_WEEKDAY_NAMES = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def _parse_hhmm(value: str) -> tuple[int, int]:
    parts = str(value).strip().split(":")
    if len(parts) != 2:
        raise ValueError("time must be HH:MM")
    hour = int(parts[0])
    minute = int(parts[1])
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        raise ValueError("time must be HH:MM")
    return hour, minute


def build_apscheduler_trigger(task: dict[str, Any]) -> Any | None:
    """Return an APScheduler trigger for time-based starts, else None."""
    start = find_start_node(task)
    if start is None:
        cron = str(task.get("cron") or "").strip()
        if cron:
            return CronTrigger.from_crontab(cron)
        return None
    kind = str(start.get("kind") or "").strip()
    if kind == "cron":
        cron = str(start.get("cron") or task.get("cron") or "").strip()
        if not cron:
            return None
        return CronTrigger.from_crontab(cron)
    if kind == "daily":
        hour, minute = _parse_hhmm(str(start.get("time") or ""))
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
        when = datetime.fromisoformat(raw)
        return DateTrigger(run_date=when)
    if kind == "interval":
        seconds = int(start.get("interval_seconds") or 0)
        if seconds < 1:
            return None
        return IntervalTrigger(seconds=seconds)
    return None
