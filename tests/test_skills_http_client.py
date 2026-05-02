"""Tests for Undefined.skills.http_client and http_config helpers."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import httpx
import pytest

import Undefined.skills.http_client as http_client_module
import Undefined.skills.http_config as http_config_module
from Undefined.skills.http_client import _retry_delay, _should_retry_http_status


class _FakeResponse:
    def __init__(self, status_code: int = 200) -> None:
        self.status_code = status_code
        self.headers: dict[str, str] = {}
        self.text = ""
        self.content = b""

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise AssertionError("unexpected status in fake response")


class TestShouldRetryHttpStatus:
    """Tests for _should_retry_http_status()."""

    def test_429_should_retry(self) -> None:
        assert _should_retry_http_status(429) is True

    def test_500_should_retry(self) -> None:
        assert _should_retry_http_status(500) is True

    def test_502_should_retry(self) -> None:
        assert _should_retry_http_status(502) is True

    def test_503_should_retry(self) -> None:
        assert _should_retry_http_status(503) is True

    def test_504_should_retry(self) -> None:
        assert _should_retry_http_status(504) is True

    def test_599_should_retry(self) -> None:
        assert _should_retry_http_status(599) is True

    def test_200_should_not_retry(self) -> None:
        assert _should_retry_http_status(200) is False

    def test_201_should_not_retry(self) -> None:
        assert _should_retry_http_status(201) is False

    def test_400_should_not_retry(self) -> None:
        assert _should_retry_http_status(400) is False

    def test_401_should_not_retry(self) -> None:
        assert _should_retry_http_status(401) is False

    def test_403_should_not_retry(self) -> None:
        assert _should_retry_http_status(403) is False

    def test_404_should_not_retry(self) -> None:
        assert _should_retry_http_status(404) is False

    def test_600_should_not_retry(self) -> None:
        assert _should_retry_http_status(600) is False

    def test_428_should_not_retry(self) -> None:
        assert _should_retry_http_status(428) is False


class TestRetryDelay:
    """Tests for _retry_delay()."""

    def test_attempt_0(self) -> None:
        assert _retry_delay(0) == 0.25  # min(2.0, 0.25 * 2^0) = 0.25

    def test_attempt_1(self) -> None:
        assert _retry_delay(1) == 0.5  # min(2.0, 0.25 * 2^1) = 0.5

    def test_attempt_2(self) -> None:
        assert _retry_delay(2) == 1.0  # min(2.0, 0.25 * 2^2) = 1.0

    def test_attempt_3(self) -> None:
        assert _retry_delay(3) == 2.0  # min(2.0, 0.25 * 2^3) = 2.0

    def test_attempt_4_capped(self) -> None:
        assert _retry_delay(4) == 2.0  # min(2.0, 0.25 * 2^4) = min(2.0, 4.0) = 2.0

    def test_attempt_5_capped(self) -> None:
        assert _retry_delay(5) == 2.0  # capped at 2.0

    def test_returns_float(self) -> None:
        assert isinstance(_retry_delay(0), float)


class TestRequestProxy:
    def test_prefers_scheme_specific_proxy(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            http_config_module,
            "get_config",
            lambda strict=False: SimpleNamespace(
                use_proxy=True,
                http_proxy="http://http-proxy.local:7890",
                https_proxy="http://https-proxy.local:7890",
            ),
        )

        assert (
            http_config_module.get_request_proxy(
                "https://api.github.com/repos/69gg/Undefined"
            )
            == "http://https-proxy.local:7890"
        )
        assert (
            http_config_module.get_request_proxy("http://example.com/resource")
            == "http://http-proxy.local:7890"
        )

    def test_returns_none_when_proxy_disabled(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            http_config_module,
            "get_config",
            lambda strict=False: SimpleNamespace(
                use_proxy=False,
                http_proxy="http://http-proxy.local:7890",
                https_proxy="http://https-proxy.local:7890",
            ),
        )

        assert (
            http_config_module.get_request_proxy(
                "https://api.github.com/repos/69gg/Undefined"
            )
            is None
        )


class TestRequestWithRetryProxy:
    @pytest.mark.asyncio
    async def test_passes_proxy_to_async_client(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client_init_kwargs: dict[str, Any] = {}
        request_kwargs: dict[str, Any] = {}

        class FakeAsyncClient:
            def __init__(self, **kwargs: Any) -> None:
                client_init_kwargs.update(kwargs)

            async def __aenter__(self) -> FakeAsyncClient:
                return self

            async def __aexit__(
                self,
                _exc_type: object,
                _exc: object,
                _tb: object,
            ) -> None:
                return None

            async def request(self, **kwargs: Any) -> _FakeResponse:
                request_kwargs.update(kwargs)
                return _FakeResponse()

        monkeypatch.setattr(
            http_client_module, "get_request_timeout", lambda _default: 12.0
        )
        monkeypatch.setattr(
            http_client_module, "get_request_retries", lambda _default: 0
        )
        monkeypatch.setattr(
            http_client_module,
            "get_request_proxy",
            lambda _url: "http://proxy.local:7890",
        )
        monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)

        response = await http_client_module.request_with_retry(
            "GET",
            "https://api.github.com/repos/69gg/Undefined",
            headers={"Accept": "application/json"},
            follow_redirects=True,
        )

        assert response.status_code == 200
        assert client_init_kwargs["proxy"] == "http://proxy.local:7890"
        assert client_init_kwargs["trust_env"] is False
        assert request_kwargs["url"] == "https://api.github.com/repos/69gg/Undefined"

    @pytest.mark.asyncio
    async def test_skips_proxy_when_not_configured(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client_init_kwargs: dict[str, Any] = {}

        class FakeAsyncClient:
            def __init__(self, **kwargs: Any) -> None:
                client_init_kwargs.update(kwargs)

            async def __aenter__(self) -> FakeAsyncClient:
                return self

            async def __aexit__(
                self,
                _exc_type: object,
                _exc: object,
                _tb: object,
            ) -> None:
                return None

            async def request(self, **_kwargs: Any) -> _FakeResponse:
                return _FakeResponse()

        monkeypatch.setattr(
            http_client_module, "get_request_timeout", lambda _default: 12.0
        )
        monkeypatch.setattr(
            http_client_module, "get_request_retries", lambda _default: 0
        )
        monkeypatch.setattr(http_client_module, "get_request_proxy", lambda _url: None)
        monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)

        await http_client_module.request_with_retry(
            "GET",
            "https://api.github.com/repos/69gg/Undefined",
        )

        assert "proxy" not in client_init_kwargs
        assert client_init_kwargs["trust_env"] is False
