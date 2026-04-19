"""Tests for Undefined.utils.cors — CORS origin helpers."""

from __future__ import annotations

from Undefined.utils.cors import is_allowed_cors_origin, normalize_origin


class TestNormalizeOrigin:
    def test_simple_origin(self) -> None:
        assert normalize_origin("http://example.com") == "http://example.com"

    def test_trailing_slash(self) -> None:
        assert normalize_origin("http://example.com/") == "http://example.com"

    def test_multiple_trailing_slashes(self) -> None:
        assert normalize_origin("http://example.com///") == "http://example.com"

    def test_case_insensitive(self) -> None:
        assert normalize_origin("HTTP://EXAMPLE.COM") == "http://example.com"

    def test_whitespace_stripped(self) -> None:
        assert normalize_origin("  http://example.com  ") == "http://example.com"

    def test_empty_string(self) -> None:
        assert normalize_origin("") == ""

    def test_none_like_empty(self) -> None:
        # The function casts to str via `str(origin or "")`.
        assert normalize_origin("") == ""

    def test_with_port(self) -> None:
        assert normalize_origin("http://localhost:8080/") == "http://localhost:8080"


class TestIsAllowedCorsOrigin:
    def test_empty_origin_rejected(self) -> None:
        assert is_allowed_cors_origin("") is False

    def test_whitespace_only_rejected(self) -> None:
        assert is_allowed_cors_origin("   ") is False

    def test_localhost_http_allowed(self) -> None:
        assert is_allowed_cors_origin("http://localhost") is True

    def test_localhost_with_port_allowed(self) -> None:
        assert is_allowed_cors_origin("http://localhost:3000") is True

    def test_localhost_https_allowed(self) -> None:
        assert is_allowed_cors_origin("https://localhost") is True

    def test_ipv4_loopback_allowed(self) -> None:
        assert is_allowed_cors_origin("http://127.0.0.1") is True

    def test_ipv4_loopback_with_port_allowed(self) -> None:
        assert is_allowed_cors_origin("http://127.0.0.1:8080") is True

    def test_ipv6_loopback_allowed(self) -> None:
        assert is_allowed_cors_origin("http://[::1]") is True

    def test_ipv6_loopback_with_port_allowed(self) -> None:
        assert is_allowed_cors_origin("http://[::1]:8080") is True

    def test_tauri_localhost_allowed(self) -> None:
        assert is_allowed_cors_origin("tauri://localhost") is True

    def test_external_origin_rejected(self) -> None:
        assert is_allowed_cors_origin("http://evil.com") is False

    def test_configured_host_allowed(self) -> None:
        assert (
            is_allowed_cors_origin(
                "http://myhost.local",
                configured_host="myhost.local",
            )
            is True
        )

    def test_configured_host_with_port(self) -> None:
        assert (
            is_allowed_cors_origin(
                "https://myhost.local:9090",
                configured_host="myhost.local",
                configured_port=9090,
            )
            is True
        )

    def test_configured_host_wrong_port_rejected(self) -> None:
        assert (
            is_allowed_cors_origin(
                "http://myhost.local:1234",
                configured_host="myhost.local",
                configured_port=9090,
            )
            is False
        )

    def test_extra_origins_allowed(self) -> None:
        assert (
            is_allowed_cors_origin(
                "https://cdn.example.com",
                extra_origins={"https://cdn.example.com"},
            )
            is True
        )

    def test_extra_origins_case_insensitive(self) -> None:
        assert (
            is_allowed_cors_origin(
                "HTTPS://CDN.EXAMPLE.COM",
                extra_origins={"https://cdn.example.com"},
            )
            is True
        )

    def test_extra_origins_not_matching_rejected(self) -> None:
        assert (
            is_allowed_cors_origin(
                "https://other.com",
                extra_origins={"https://cdn.example.com"},
            )
            is False
        )

    def test_no_scheme_rejected(self) -> None:
        # "example.com" without scheme is not a valid loopback HTTP origin
        assert is_allowed_cors_origin("example.com") is False

    def test_ftp_scheme_rejected(self) -> None:
        assert is_allowed_cors_origin("ftp://localhost") is False

    def test_configured_host_empty(self) -> None:
        # Empty configured_host should not add anything
        assert is_allowed_cors_origin("http://evil.com", configured_host="") is False

    def test_extra_origins_none(self) -> None:
        assert is_allowed_cors_origin("http://localhost", extra_origins=None) is True
