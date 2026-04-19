"""Tests for configurable history limits in Config and tool handlers."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Helper: simulate _get_history_limit as used across multiple handlers
# ---------------------------------------------------------------------------
def _get_history_limit(context: dict[str, Any], key: str, fallback: int) -> int:
    """Mirror of the helper used in tool handlers."""
    cfg = context.get("runtime_config")
    if cfg is not None:
        val = getattr(cfg, key, None)
        if isinstance(val, int) and val > 0:
            return val
    return fallback


class TestGetHistoryLimit:
    """Tests for the _get_history_limit helper pattern."""

    def test_returns_fallback_when_no_config(self) -> None:
        assert _get_history_limit({}, "history_filtered_result_limit", 200) == 200

    def test_returns_fallback_when_config_is_none(self) -> None:
        ctx: dict[str, Any] = {"runtime_config": None}
        assert _get_history_limit(ctx, "history_filtered_result_limit", 200) == 200

    def test_returns_config_value(self) -> None:
        cfg = MagicMock()
        cfg.history_filtered_result_limit = 500
        ctx: dict[str, Any] = {"runtime_config": cfg}
        assert _get_history_limit(ctx, "history_filtered_result_limit", 200) == 500

    def test_returns_fallback_when_config_attr_missing(self) -> None:
        cfg = MagicMock(spec=[])  # no attributes
        ctx: dict[str, Any] = {"runtime_config": cfg}
        assert _get_history_limit(ctx, "nonexistent_field", 42) == 42

    def test_returns_fallback_when_config_value_zero(self) -> None:
        cfg = MagicMock()
        cfg.history_filtered_result_limit = 0
        ctx: dict[str, Any] = {"runtime_config": cfg}
        assert _get_history_limit(ctx, "history_filtered_result_limit", 200) == 200

    def test_returns_fallback_when_config_value_negative(self) -> None:
        cfg = MagicMock()
        cfg.history_filtered_result_limit = -1
        ctx: dict[str, Any] = {"runtime_config": cfg}
        assert _get_history_limit(ctx, "history_filtered_result_limit", 200) == 200


class TestConfigHistoryFieldDefaults:
    """Verify that Config dataclass has the expected history fields."""

    def test_config_has_history_fields(self) -> None:
        from Undefined.config.loader import Config

        fields = Config.__dataclass_fields__
        expected_fields = [
            "history_max_records",
            "history_filtered_result_limit",
            "history_search_scan_limit",
            "history_summary_fetch_limit",
            "history_summary_time_fetch_limit",
            "history_onebot_fetch_limit",
            "history_group_analysis_limit",
        ]
        for field_name in expected_fields:
            assert field_name in fields, f"Missing field: {field_name}"
            assert fields[field_name].type == "int", (
                f"{field_name} should be int, got {fields[field_name].type}"
            )
