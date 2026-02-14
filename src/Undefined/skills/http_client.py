from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import httpx

from Undefined.skills.http_config import get_request_retries, get_request_timeout

logger = logging.getLogger(__name__)


def _should_retry_http_status(status_code: int) -> bool:
    return status_code == 429 or 500 <= status_code < 600


def _retry_delay(attempt: int) -> float:
    return float(min(2.0, 0.25 * (2**attempt)))


async def request_with_retry(
    method: str,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    json_data: Any | None = None,
    data: Any | None = None,
    headers: dict[str, str] | None = None,
    timeout: float | None = None,
    default_timeout: float = 15.0,
    follow_redirects: bool = False,
    context: dict[str, Any] | None = None,
    retries: int | None = None,
) -> httpx.Response:
    request_timeout = (
        timeout if timeout is not None else get_request_timeout(default_timeout)
    )
    request_retries = retries if retries is not None else get_request_retries(0)
    request_id = "-"
    if context is not None:
        request_id = str(context.get("request_id", "-"))

    last_exception: Exception | None = None
    async with httpx.AsyncClient(
        timeout=request_timeout,
        follow_redirects=follow_redirects,
    ) as client:
        for attempt in range(request_retries + 1):
            try:
                response = await client.request(
                    method=method,
                    url=url,
                    params=params,
                    json=json_data,
                    data=data,
                    headers=headers,
                )
                if (
                    _should_retry_http_status(response.status_code)
                    and attempt < request_retries
                ):
                    delay = _retry_delay(attempt)
                    logger.warning(
                        "[HTTP] status retry: method=%s url=%s status=%s attempt=%s/%s wait=%.2fs request_id=%s",
                        method,
                        url,
                        response.status_code,
                        attempt + 1,
                        request_retries + 1,
                        delay,
                        request_id,
                    )
                    await asyncio.sleep(delay)
                    continue

                response.raise_for_status()
                return response
            except httpx.HTTPStatusError as exc:
                last_exception = exc
                if attempt >= request_retries:
                    break
                if not _should_retry_http_status(exc.response.status_code):
                    break
                delay = _retry_delay(attempt)
                logger.warning(
                    "[HTTP] status exception retry: method=%s url=%s status=%s attempt=%s/%s wait=%.2fs request_id=%s",
                    method,
                    url,
                    exc.response.status_code,
                    attempt + 1,
                    request_retries + 1,
                    delay,
                    request_id,
                )
                await asyncio.sleep(delay)
            except (httpx.TimeoutException, httpx.RequestError) as exc:
                last_exception = exc
                if attempt >= request_retries:
                    break
                delay = _retry_delay(attempt)
                logger.warning(
                    "[HTTP] request retry: method=%s url=%s err=%s attempt=%s/%s wait=%.2fs request_id=%s",
                    method,
                    url,
                    type(exc).__name__,
                    attempt + 1,
                    request_retries + 1,
                    delay,
                    request_id,
                )
                await asyncio.sleep(delay)

    if last_exception is not None:
        raise last_exception
    raise RuntimeError(f"HTTP request failed without exception: {method} {url}")


async def get_json_with_retry(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    timeout: float | None = None,
    default_timeout: float = 15.0,
    follow_redirects: bool = False,
    context: dict[str, Any] | None = None,
    retries: int | None = None,
) -> Any:
    request_id = "-"
    if context is not None:
        request_id = str(context.get("request_id", "-"))

    response = await request_with_retry(
        "GET",
        url,
        params=params,
        timeout=timeout,
        default_timeout=default_timeout,
        follow_redirects=follow_redirects,
        context=context,
        retries=retries,
    )
    try:
        return response.json()
    except json.JSONDecodeError as exc:
        content_type = response.headers.get("content-type", "")
        preview = response.text[:200].replace("\n", "\\n").replace("\r", "\\r")
        logger.warning(
            "[HTTP] json decode failed: url=%s status=%s content_type=%s preview=%s request_id=%s err=%s",
            url,
            response.status_code,
            content_type,
            preview,
            request_id,
            exc,
        )
        raise


async def get_text_with_retry(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    timeout: float | None = None,
    default_timeout: float = 15.0,
    follow_redirects: bool = False,
    context: dict[str, Any] | None = None,
    retries: int | None = None,
) -> str:
    response = await request_with_retry(
        "GET",
        url,
        params=params,
        timeout=timeout,
        default_timeout=default_timeout,
        follow_redirects=follow_redirects,
        context=context,
        retries=retries,
    )
    return response.text


async def get_bytes_with_retry(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    timeout: float | None = None,
    default_timeout: float = 15.0,
    follow_redirects: bool = False,
    context: dict[str, Any] | None = None,
    retries: int | None = None,
) -> bytes:
    response = await request_with_retry(
        "GET",
        url,
        params=params,
        timeout=timeout,
        default_timeout=default_timeout,
        follow_redirects=follow_redirects,
        context=context,
        retries=retries,
    )
    return response.content
