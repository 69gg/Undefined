"""Logging helpers."""

from __future__ import annotations

import json
import logging
import re
from typing import Any


_SENSITIVE_KEYWORDS: tuple[str, ...] = (
    "authorization",
    "api_key",
    "apikey",
    "access_token",
    "refresh_token",
    "id_token",
    "token",
    "secret",
    "password",
    "onebot_token",
)


_BEARER_RE = re.compile(r"(Bearer\\s+)[A-Za-z0-9\\-._~+/=]+", re.IGNORECASE)
_KV_TOKEN_RE = re.compile(
    r"(?i)(api_key|apikey|access_token|refresh_token|id_token|token|secret|password)"
    r"(\\s*[:=]\\s*)(['\\\"]?)([^'\\\"\\s]+)"
)
_SK_RE = re.compile(r"\\bsk-[A-Za-z0-9]{8,}\\b")


def _is_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    for keyword in _SENSITIVE_KEYWORDS:
        if keyword in lowered:
            return True
    return False


def redact_string(text: str) -> str:
    """Redact obvious secrets in strings."""
    if not text:
        return text
    masked = _BEARER_RE.sub(r"\\1***", text)
    masked = _KV_TOKEN_RE.sub(r"\\1\\2\\3***", masked)
    masked = _SK_RE.sub("sk-***", masked)
    return masked


def sanitize_data(payload: Any) -> Any:
    """Recursively sanitize payloads to avoid leaking secrets in logs."""
    if isinstance(payload, dict):
        sanitized: dict[str, Any] = {}
        for key, value in payload.items():
            key_str = str(key)
            if _is_sensitive_key(key_str):
                sanitized[key_str] = "***"
            else:
                sanitized[key_str] = sanitize_data(value)
        return sanitized
    if isinstance(payload, list):
        return [sanitize_data(item) for item in payload]
    if isinstance(payload, tuple):
        return tuple(sanitize_data(item) for item in payload)
    if isinstance(payload, set):
        return {sanitize_data(item) for item in payload}
    if isinstance(payload, str):
        return redact_string(payload)
    return payload


def log_debug_json(logger: logging.Logger, prefix: str, payload: Any) -> None:
    """Log a JSON payload at DEBUG level with safe fallback serialization."""
    if not logger.isEnabledFor(logging.DEBUG):
        return
    safe_payload = sanitize_data(payload)
    try:
        dumped = json.dumps(safe_payload, ensure_ascii=False, indent=2, default=str)
    except (TypeError, ValueError):
        dumped = str(safe_payload)
    logger.debug("%s\n%s", prefix, dumped)
