"""LLM HTTP 错误判定与有限次重试。"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

import httpx
from anthropic import APIStatusError as AnthropicAPIStatusError
from openai import APIStatusError as OpenAIAPIStatusError

T = TypeVar("T")


def http_status_code(exc: BaseException) -> int | None:
    if isinstance(exc, (OpenAIAPIStatusError, AnthropicAPIStatusError)):
        try:
            return int(exc.status_code)
        except (TypeError, ValueError):
            return None
    if isinstance(exc, httpx.HTTPStatusError):
        response = getattr(exc, "response", None)
        status = getattr(response, "status_code", None)
        try:
            return int(status) if status is not None else None
        except (TypeError, ValueError):
            return None
    return None


def is_retryable_http_error(exc: BaseException) -> bool:
    """429 与 5xx 视为可重试的请求 HTTP 错误。"""
    status = http_status_code(exc)
    if status is None:
        return False
    return status == 429 or status >= 500


def _retry_delay(attempt: int) -> float:
    return float(min(2.0, 0.25 * (2**attempt)))


async def request_with_http_retries(
    request: Callable[..., Awaitable[T]],
    /,
    *args: Any,
    max_retries: int,
    log_prefix: str,
    log: logging.Logger,
    **kwargs: Any,
) -> T:
    retries = max(0, int(max_retries or 0))
    for attempt in range(retries + 1):
        try:
            return await request(*args, **kwargs)
        except Exception as exc:
            if attempt >= retries or not is_retryable_http_error(exc):
                raise
            delay = _retry_delay(attempt)
            log.warning(
                "%s HTTP 错误重试: retry=%s/%s status=%s wait=%.2fs error=%s",
                log_prefix,
                attempt + 1,
                retries,
                http_status_code(exc),
                delay,
                exc,
            )
            await asyncio.sleep(delay)
    raise RuntimeError("request_with_http_retries exhausted without result")
