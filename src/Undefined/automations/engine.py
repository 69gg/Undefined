"""Match inbound events against enabled automations."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from Undefined.automations.constants import DEFAULT_EVENT_COOLDOWN_SECONDS, EVENT_KINDS
from Undefined.automations.logutil import preview_text
from Undefined.automations.match import AutomationEvent, StartMatch, match_start_node
from Undefined.automations.runner import find_start_node, start_kind

logger = logging.getLogger(__name__)


def _parse_iso(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _cooldown_seconds(task: dict[str, Any], default: int) -> int:
    raw = task.get("cooldown_seconds")
    if raw is None or raw == "":
        kind = start_kind(task)
        return default if kind in EVENT_KINDS else 0
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return max(0, value)


def cooldown_active(
    task: dict[str, Any],
    *,
    now: datetime,
    default_seconds: int = DEFAULT_EVENT_COOLDOWN_SECONDS,
) -> bool:
    seconds = _cooldown_seconds(task, default_seconds)
    if seconds <= 0:
        return False
    last = _parse_iso(task.get("last_run_at"))
    if last is None:
        return False
    current = now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)
    if last.tzinfo is None:
        last = last.replace(tzinfo=current.tzinfo)
    return (current - last).total_seconds() < seconds


def iter_matching_tasks(
    tasks: dict[str, Any],
    event: AutomationEvent,
    *,
    now: datetime | None = None,
    running_ids: set[str] | None = None,
    default_cooldown: int = DEFAULT_EVENT_COOLDOWN_SECONDS,
) -> list[tuple[str, dict[str, Any], StartMatch]]:
    """Return enabled automations that match ``event``, in insertion order."""
    matched: list[tuple[str, dict[str, Any], StartMatch]] = []
    current = now or datetime.now().astimezone()
    busy = running_ids or set()
    for task_id, task in tasks.items():
        if not isinstance(task, dict):
            continue
        if task.get("enabled") is False:
            logger.debug("[自动化] 匹配跳过停用: id=%s", task_id)
            continue
        if task_id in busy:
            logger.debug("[自动化] 匹配跳过运行中: id=%s", task_id)
            continue
        start = find_start_node(task)
        if start is None:
            logger.debug("[自动化] 匹配跳过无 start: id=%s", task_id)
            continue
        result = match_start_node(start, event, now=current)
        if result is None:
            logger.debug(
                "[自动化] 未命中: id=%s start_kind=%s event=%s channel=%s",
                task_id,
                str(start.get("kind") or ""),
                event.kind,
                event.channel,
            )
            continue
        if cooldown_active(task, now=current, default_seconds=default_cooldown):
            logger.info(
                "[自动化] 冷却中，跳过: id=%s last_run=%s preview=%s",
                task_id,
                task.get("last_run_at") or "-",
                preview_text(result.pass_text),
            )
            continue
        matched.append((task_id, task, result))
    return matched
