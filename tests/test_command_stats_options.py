from __future__ import annotations

from Undefined.services.command import CommandDispatcher


def _dispatcher_for_parse() -> CommandDispatcher:
    return object.__new__(CommandDispatcher)


def test_parse_stats_options_defaults() -> None:
    dispatcher = _dispatcher_for_parse()
    days, enable_ai = dispatcher._parse_stats_options([])
    assert days == 7
    assert enable_ai is False


def test_parse_stats_options_time_only() -> None:
    dispatcher = _dispatcher_for_parse()
    days, enable_ai = dispatcher._parse_stats_options(["30d"])
    assert days == 30
    assert enable_ai is False


def test_parse_stats_options_ai_only() -> None:
    dispatcher = _dispatcher_for_parse()
    days, enable_ai = dispatcher._parse_stats_options(["--ai"])
    assert days == 7
    assert enable_ai is True


def test_parse_stats_options_supports_flag_and_time_any_order() -> None:
    dispatcher = _dispatcher_for_parse()
    days1, enable_ai1 = dispatcher._parse_stats_options(["--ai", "2w"])
    days2, enable_ai2 = dispatcher._parse_stats_options(["2w", "-a"])
    assert days1 == 14
    assert enable_ai1 is True
    assert days2 == 14
    assert enable_ai2 is True
