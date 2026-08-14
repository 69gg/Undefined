from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from openai import APIStatusError

from Undefined.ai.llm.retry import (
    http_status_code,
    is_retryable_http_error,
    request_with_http_retries,
)
from Undefined.services.security import SecurityService


def _make_api_status_error(status_code: int) -> APIStatusError:
    response = MagicMock()
    response.status_code = status_code
    response.headers = {}
    response.text = ""
    response.json.return_value = {}
    return APIStatusError(
        message=f"Error {status_code}",
        response=response,
        body=None,
    )


def _make_httpx_status_error(status_code: int) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://example.test/v1/chat/completions")
    response = httpx.Response(status_code, request=request)
    return httpx.HTTPStatusError(
        f"HTTP {status_code}",
        request=request,
        response=response,
    )


def test_retryable_http_status_codes() -> None:
    assert is_retryable_http_error(_make_api_status_error(429)) is True
    assert is_retryable_http_error(_make_api_status_error(500)) is True
    assert is_retryable_http_error(_make_api_status_error(503)) is True
    assert is_retryable_http_error(_make_httpx_status_error(502)) is True
    assert is_retryable_http_error(_make_api_status_error(400)) is False
    assert is_retryable_http_error(_make_api_status_error(401)) is False
    assert is_retryable_http_error(ValueError("parse")) is False
    assert http_status_code(_make_api_status_error(503)) == 503


@pytest.mark.asyncio
async def test_request_with_http_retries_retries_then_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    slept: list[float] = []

    async def fake_sleep(delay: float) -> None:
        slept.append(delay)

    monkeypatch.setattr("Undefined.ai.llm.retry.asyncio.sleep", fake_sleep)

    calls = {"n": 0}

    async def flaky(**_kwargs: Any) -> dict[str, str]:
        calls["n"] += 1
        if calls["n"] < 3:
            raise _make_api_status_error(500)
        return {"ok": "yes"}

    result = await request_with_http_retries(
        flaky,
        max_retries=2,
        log_prefix="[test]",
        log=MagicMock(),
    )
    assert result == {"ok": "yes"}
    assert calls["n"] == 3
    assert slept == [0.25, 0.5]


@pytest.mark.asyncio
async def test_request_with_http_retries_does_not_retry_client_error() -> None:
    calls = {"n": 0}

    async def fail_400(**_kwargs: Any) -> dict[str, str]:
        calls["n"] += 1
        raise _make_api_status_error(400)

    with pytest.raises(APIStatusError):
        await request_with_http_retries(
            fail_400,
            max_retries=2,
            log_prefix="[test]",
            log=MagicMock(),
        )
    assert calls["n"] == 1


def _safe_response() -> dict[str, Any]:
    return {"choices": [{"message": {"content": "SAFE"}}]}


def _build_security_service(requester: Any, *, max_retries: int) -> SecurityService:
    service = object.__new__(SecurityService)
    model_config = SimpleNamespace(
        api_mode="chat_completions",
        thinking_enabled=False,
        model_name="security-model",
    )
    service.config = cast(
        Any,
        SimpleNamespace(
            security_check_enabled=lambda: True,
            security_model=model_config,
            naga_model=model_config,
            ai_request_max_retries=max_retries,
        ),
    )
    service._requester = requester
    return service


@pytest.mark.asyncio
async def test_detect_injection_retries_http_500_then_passes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("Undefined.ai.llm.retry.asyncio.sleep", AsyncMock())

    class _FlakyRequester:
        def __init__(self) -> None:
            self.calls = 0

        async def request(self, **kwargs: Any) -> dict[str, Any]:
            _ = kwargs
            self.calls += 1
            if self.calls < 2:
                raise _make_api_status_error(500)
            return _safe_response()

    requester = _FlakyRequester()
    service = _build_security_service(requester, max_retries=2)
    assert await service.detect_injection("hello") is False
    assert requester.calls == 2


@pytest.mark.asyncio
async def test_detect_injection_http_400_is_not_retried_and_fail_closed() -> None:
    class _ClientErrorRequester:
        def __init__(self) -> None:
            self.calls = 0

        async def request(self, **kwargs: Any) -> dict[str, Any]:
            _ = kwargs
            self.calls += 1
            raise _make_api_status_error(400)

    requester = _ClientErrorRequester()
    service = _build_security_service(requester, max_retries=2)
    assert await service.detect_injection("hello") is True
    assert requester.calls == 1


@pytest.mark.asyncio
async def test_detect_injection_exhausts_http_retries_and_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("Undefined.ai.llm.retry.asyncio.sleep", AsyncMock())

    class _Always500Requester:
        def __init__(self) -> None:
            self.calls = 0

        async def request(self, **kwargs: Any) -> dict[str, Any]:
            _ = kwargs
            self.calls += 1
            raise _make_api_status_error(503)

    requester = _Always500Requester()
    service = _build_security_service(requester, max_retries=2)
    assert await service.detect_injection("hello") is True
    assert requester.calls == 3


@pytest.mark.asyncio
async def test_detect_injection_zero_retries_does_not_retry() -> None:
    class _Always500Requester:
        def __init__(self) -> None:
            self.calls = 0

        async def request(self, **kwargs: Any) -> dict[str, Any]:
            _ = kwargs
            self.calls += 1
            raise _make_httpx_status_error(502)

    requester = _Always500Requester()
    service = _build_security_service(requester, max_retries=0)
    assert await service.detect_injection("hello") is True
    assert requester.calls == 1


@pytest.mark.asyncio
async def test_moderate_naga_message_retries_http_429(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("Undefined.ai.llm.retry.asyncio.sleep", AsyncMock())

    class _FlakyRequester:
        def __init__(self) -> None:
            self.calls = 0

        async def request(self, **kwargs: Any) -> dict[str, Any]:
            _ = kwargs
            self.calls += 1
            if self.calls < 2:
                raise _make_api_status_error(429)
            return {
                "choices": [
                    {
                        "message": {
                            "tool_calls": [
                                {
                                    "function": {
                                        "name": "submit_naga_moderation_result",
                                        "arguments": (
                                            '{"decision":"allow",'
                                            '"categories":[],'
                                            '"reason":"ok"}'
                                        ),
                                    }
                                }
                            ]
                        }
                    }
                ]
            }

    requester = _FlakyRequester()
    service = _build_security_service(requester, max_retries=1)
    result = await service.moderate_naga_message(
        message_format="text",
        content="hello",
    )
    assert result.blocked is False
    assert result.status == "passed"
    assert requester.calls == 2
