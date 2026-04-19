"""Tests for Undefined.skills.http_client module (pure functions only)."""

from __future__ import annotations

from Undefined.skills.http_client import _retry_delay, _should_retry_http_status


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
