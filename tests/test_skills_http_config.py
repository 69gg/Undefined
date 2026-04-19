"""Tests for Undefined.skills.http_config module (pure functions only)."""

from __future__ import annotations

from Undefined.skills.http_config import _normalize_base_url, build_url


class TestBuildUrl:
    """Tests for build_url()."""

    def test_simple_join(self) -> None:
        assert (
            build_url("https://api.example.com", "/v1/data")
            == "https://api.example.com/v1/data"
        )

    def test_trailing_slash_on_base(self) -> None:
        assert (
            build_url("https://api.example.com/", "/v1/data")
            == "https://api.example.com/v1/data"
        )

    def test_multiple_trailing_slashes(self) -> None:
        assert (
            build_url("https://api.example.com///", "/v1")
            == "https://api.example.com/v1"
        )

    def test_path_without_leading_slash(self) -> None:
        assert (
            build_url("https://api.example.com", "v1/data")
            == "https://api.example.com/v1/data"
        )

    def test_empty_path(self) -> None:
        assert build_url("https://api.example.com", "") == "https://api.example.com/"

    def test_path_is_slash_only(self) -> None:
        assert build_url("https://api.example.com", "/") == "https://api.example.com/"

    def test_base_with_subpath(self) -> None:
        assert (
            build_url("https://api.example.com/v2", "/users")
            == "https://api.example.com/v2/users"
        )

    def test_base_with_subpath_trailing_slash(self) -> None:
        assert (
            build_url("https://api.example.com/v2/", "/users")
            == "https://api.example.com/v2/users"
        )


class TestNormalizeBaseUrl:
    """Tests for _normalize_base_url()."""

    def test_normal_url(self) -> None:
        assert (
            _normalize_base_url("https://api.example.com", "https://fallback.com")
            == "https://api.example.com"
        )

    def test_trailing_slash_removed(self) -> None:
        assert (
            _normalize_base_url("https://api.example.com/", "https://fallback.com")
            == "https://api.example.com"
        )

    def test_multiple_trailing_slashes(self) -> None:
        assert (
            _normalize_base_url("https://api.example.com///", "https://fallback.com")
            == "https://api.example.com"
        )

    def test_empty_value_uses_fallback(self) -> None:
        assert _normalize_base_url("", "https://fallback.com") == "https://fallback.com"

    def test_whitespace_only_uses_fallback(self) -> None:
        assert (
            _normalize_base_url("   ", "https://fallback.com") == "https://fallback.com"
        )

    def test_fallback_trailing_slash_stripped(self) -> None:
        assert (
            _normalize_base_url("", "https://fallback.com/") == "https://fallback.com"
        )

    def test_leading_trailing_whitespace_stripped(self) -> None:
        assert (
            _normalize_base_url("  https://api.example.com  ", "https://fallback.com")
            == "https://api.example.com"
        )

    def test_value_with_path(self) -> None:
        assert (
            _normalize_base_url("https://api.example.com/v2/", "https://fallback.com")
            == "https://api.example.com/v2"
        )
