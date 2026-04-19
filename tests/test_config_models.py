"""Tests for Undefined.config.models — config model helpers."""

from __future__ import annotations

from Undefined.config.models import format_netloc, resolve_bind_hosts


class TestFormatNetloc:
    def test_ipv4(self) -> None:
        assert format_netloc("127.0.0.1", 8080) == "127.0.0.1:8080"

    def test_hostname(self) -> None:
        assert format_netloc("example.com", 443) == "example.com:443"

    def test_ipv6_wrapped(self) -> None:
        assert format_netloc("::1", 8080) == "[::1]:8080"

    def test_ipv6_full(self) -> None:
        result = format_netloc("2001:db8::1", 9090)
        assert result == "[2001:db8::1]:9090"

    def test_ipv6_all_zeros(self) -> None:
        assert format_netloc("::", 80) == "[::]:80"

    def test_ipv4_default_port(self) -> None:
        assert format_netloc("0.0.0.0", 80) == "0.0.0.0:80"

    def test_localhost(self) -> None:
        assert format_netloc("localhost", 3000) == "localhost:3000"

    def test_empty_host(self) -> None:
        # No colon in empty string → treated as IPv4-style
        assert format_netloc("", 8080) == ":8080"


class TestResolveBindHosts:
    def test_empty_string(self) -> None:
        assert resolve_bind_hosts("") == ["0.0.0.0", "::"]

    def test_double_colon(self) -> None:
        assert resolve_bind_hosts("::") == ["0.0.0.0", "::"]

    def test_ipv4_any(self) -> None:
        assert resolve_bind_hosts("0.0.0.0") == ["0.0.0.0"]

    def test_specific_ipv4(self) -> None:
        assert resolve_bind_hosts("127.0.0.1") == ["127.0.0.1"]

    def test_specific_ipv6(self) -> None:
        assert resolve_bind_hosts("::1") == ["::1"]

    def test_hostname(self) -> None:
        assert resolve_bind_hosts("myhost.local") == ["myhost.local"]
