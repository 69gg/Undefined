"""HTTP/WebSocket endpoint probe functions for health checks."""

from __future__ import annotations

import asyncio
import logging
import socket
import time
from typing import Any
from urllib.parse import urlsplit

from aiohttp import ClientSession, ClientTimeout

from ._helpers import _mask_url

logger = logging.getLogger(__name__)


async def _probe_http_endpoint(
    *,
    name: str,
    base_url: str,
    api_key: str,
    model_name: str = "",
    timeout_seconds: float = 5.0,
) -> dict[str, Any]:
    normalized = str(base_url or "").strip().rstrip("/")
    if not normalized:
        return {
            "name": name,
            "status": "skipped",
            "reason": "empty_url",
            "model_name": model_name,
        }

    headers: dict[str, str] = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    candidates = [normalized, f"{normalized}/models"]
    last_error = ""
    for url in candidates:
        start = time.perf_counter()
        try:
            timeout = ClientTimeout(total=timeout_seconds)
            async with ClientSession(timeout=timeout) as session:
                async with session.get(url, headers=headers) as resp:
                    elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
                    return {
                        "name": name,
                        "status": "ok",
                        "url": _mask_url(url),
                        "http_status": resp.status,
                        "latency_ms": elapsed_ms,
                        "model_name": model_name,
                    }
        except Exception as exc:
            last_error = str(exc)
            continue

    return {
        "name": name,
        "status": "error",
        "url": _mask_url(normalized),
        "error": last_error or "request_failed",
        "model_name": model_name,
    }


async def _skipped_probe(
    *, name: str, reason: str, model_name: str = ""
) -> dict[str, Any]:
    payload: dict[str, Any] = {"name": name, "status": "skipped", "reason": reason}
    if model_name:
        payload["model_name"] = model_name
    return payload


def _build_internal_model_probe_payload(mcfg: Any) -> dict[str, Any]:
    payload = {
        "model_name": getattr(mcfg, "model_name", ""),
        "api_url": _mask_url(getattr(mcfg, "api_url", "")),
    }
    if hasattr(mcfg, "api_mode"):
        payload["api_mode"] = getattr(mcfg, "api_mode", "chat_completions")
    if hasattr(mcfg, "thinking_enabled"):
        payload["thinking_enabled"] = getattr(mcfg, "thinking_enabled", False)
    if hasattr(mcfg, "thinking_tool_call_compat"):
        payload["thinking_tool_call_compat"] = getattr(
            mcfg, "thinking_tool_call_compat", True
        )
    if hasattr(mcfg, "responses_tool_choice_compat"):
        payload["responses_tool_choice_compat"] = getattr(
            mcfg, "responses_tool_choice_compat", False
        )
    if hasattr(mcfg, "responses_force_stateless_replay"):
        payload["responses_force_stateless_replay"] = getattr(
            mcfg, "responses_force_stateless_replay", False
        )
    if hasattr(mcfg, "prompt_cache_enabled"):
        payload["prompt_cache_enabled"] = getattr(mcfg, "prompt_cache_enabled", True)
    if hasattr(mcfg, "reasoning_enabled"):
        payload["reasoning_enabled"] = getattr(mcfg, "reasoning_enabled", False)
    if hasattr(mcfg, "reasoning_effort"):
        payload["reasoning_effort"] = getattr(mcfg, "reasoning_effort", "medium")
    return payload


async def _probe_ws_endpoint(url: str, timeout_seconds: float = 5.0) -> dict[str, Any]:
    normalized = str(url or "").strip()
    if not normalized:
        return {"name": "onebot_ws", "status": "skipped", "reason": "empty_url"}

    parsed = urlsplit(normalized)
    host = parsed.hostname
    if not host:
        return {"name": "onebot_ws", "status": "error", "error": "invalid_url"}

    if parsed.port is not None:
        port = parsed.port
    elif parsed.scheme == "wss":
        port = 443
    else:
        port = 80

    start = time.perf_counter()
    try:
        conn = asyncio.open_connection(host, port)
        reader, writer = await asyncio.wait_for(conn, timeout=timeout_seconds)
        writer.close()
        await writer.wait_closed()
        elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
        return {
            "name": "onebot_ws",
            "status": "ok",
            "host": host,
            "port": port,
            "latency_ms": elapsed_ms,
        }
    except (OSError, TimeoutError, socket.gaierror, asyncio.TimeoutError) as exc:
        return {
            "name": "onebot_ws",
            "status": "error",
            "host": host,
            "port": port,
            "error": str(exc),
        }
