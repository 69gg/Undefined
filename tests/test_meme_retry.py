from __future__ import annotations


from openai import APIConnectionError, APIStatusError, APITimeoutError
from unittest.mock import MagicMock

from Undefined.memes.service import _is_retryable_llm_error


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


def test_connection_error_is_retryable() -> None:
    exc = APIConnectionError(request=MagicMock())
    assert _is_retryable_llm_error(exc) is True


def test_timeout_error_is_retryable() -> None:
    exc = APITimeoutError(request=MagicMock())
    assert _is_retryable_llm_error(exc) is True


def test_status_429_is_retryable() -> None:
    exc = _make_api_status_error(429)
    assert _is_retryable_llm_error(exc) is True


def test_status_500_is_retryable() -> None:
    exc = _make_api_status_error(500)
    assert _is_retryable_llm_error(exc) is True


def test_status_503_is_retryable() -> None:
    exc = _make_api_status_error(503)
    assert _is_retryable_llm_error(exc) is True


def test_status_401_not_retryable() -> None:
    exc = _make_api_status_error(401)
    assert _is_retryable_llm_error(exc) is False


def test_status_400_not_retryable() -> None:
    exc = _make_api_status_error(400)
    assert _is_retryable_llm_error(exc) is False


def test_generic_exception_not_retryable() -> None:
    assert _is_retryable_llm_error(ValueError("parse fail")) is False


def test_runtime_error_not_retryable() -> None:
    assert _is_retryable_llm_error(RuntimeError("oops")) is False
