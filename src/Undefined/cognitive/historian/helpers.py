"""Historian 辅助函数。"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

_MAX_LOG_PREVIEW_LEN = 200


def _preview_text(text: str, max_len: int = _MAX_LOG_PREVIEW_LEN) -> str:
    compact = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(compact) <= max_len:
        return compact
    return f"{compact[:max_len]}..."


def _extract_frontmatter_name(markdown: str) -> str:
    text = str(markdown or "")
    if not text.startswith("---"):
        return ""
    try:
        import yaml

        parts = text[3:].split("---", 1)
        if len(parts) != 2:
            return ""
        frontmatter = yaml.safe_load(parts[0])
        if not isinstance(frontmatter, dict):
            return ""
        value = frontmatter.get("name")
        return str(value).strip() if value is not None else ""
    except Exception:
        return ""


def _escape_braces(text: str) -> str:
    value = str(text or "")
    return value.replace("{", "{{").replace("}", "}}")


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
