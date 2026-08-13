"""Historian 辅助函数。"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone, tzinfo
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

logger = logging.getLogger(__name__)

_MAX_LOG_PREVIEW_LEN = 200


def _preview_text(text: str, max_len: int = _MAX_LOG_PREVIEW_LEN) -> str:
    compact = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(compact) <= max_len:
        return compact
    return f"{compact[:max_len]}..."


def _extract_frontmatter_dict(markdown: str) -> dict[str, Any]:
    text = str(markdown or "")
    if not text.startswith("---"):
        return {}
    try:
        import yaml

        parts = text[3:].split("---", 1)
        if len(parts) != 2:
            return {}
        frontmatter = yaml.safe_load(parts[0])
        if not isinstance(frontmatter, dict):
            return {}
        return frontmatter
    except Exception:
        return {}


def _extract_frontmatter_name(markdown: str) -> str:
    frontmatter = _extract_frontmatter_dict(markdown)
    value = frontmatter.get("name")
    return str(value).strip() if value is not None else ""


def _extract_frontmatter_updated_at(markdown: str) -> str:
    frontmatter = _extract_frontmatter_dict(markdown)
    value = frontmatter.get("updated_at")
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value).strip()


def _escape_braces(text: str) -> str:
    value = str(text or "")
    return value.replace("{", "{{").replace("}", "}}")


def _resolve_job_timezone(job: dict[str, Any]) -> tuple[tzinfo, str]:
    """用 ZoneInfo 解析 job 时区；无效或缺失时回退到系统本地时区。"""
    raw = str(job.get("timezone") or "").strip()
    if raw:
        try:
            return ZoneInfo(raw), raw
        except (ZoneInfoNotFoundError, ValueError, OSError):
            pass
    fallback = datetime.now().astimezone()
    fallback_tz = fallback.tzinfo or timezone.utc
    label = getattr(fallback_tz, "key", None) or str(fallback_tz) or "UTC"
    return fallback_tz, str(label)


def _now_in_job_timezone(job: dict[str, Any]) -> tuple[datetime, datetime, str]:
    """同一瞬间的本地时刻、UTC 时刻与时区标签。"""
    tz, label = _resolve_job_timezone(job)
    now_utc = datetime.now(timezone.utc)
    now_local = now_utc.astimezone(tz)
    return now_local, now_utc, label


def _resolve_timestamp_epoch(job: dict[str, Any]) -> int:
    raw_epoch = job.get("timestamp_epoch")
    if isinstance(raw_epoch, (int, float)):
        return int(raw_epoch)
    if isinstance(raw_epoch, str):
        try:
            return int(float(raw_epoch.strip()))
        except Exception:
            pass

    for key in ("timestamp_utc", "timestamp_local"):
        raw_value = job.get(key)
        if not isinstance(raw_value, str):
            continue
        text = raw_value.strip()
        if not text:
            continue
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return int(parsed.timestamp())
        except Exception:
            continue

    return int(datetime.now(timezone.utc).timestamp())


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "y", "on"}:
            return True
        if normalized in {"0", "false", "no", "n", "off", ""}:
            return False
    return False
