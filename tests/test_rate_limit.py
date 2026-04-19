"""RateLimiter 单元测试"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, cast

from Undefined.rate_limit import RateLimiter


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------


class _MockConfig:
    """最小化的 Config mock。"""

    def __init__(
        self,
        superadmins: set[int] | None = None,
        admins: set[int] | None = None,
    ) -> None:
        self._superadmins = superadmins or set()
        self._admins = admins or set()

    def is_superadmin(self, user_id: int) -> bool:
        return user_id in self._superadmins

    def is_admin(self, user_id: int) -> bool:
        return user_id in self._admins


@dataclass
class _MockCommandRateLimit:
    """模拟 CommandRateLimit。"""

    user: int = 10
    admin: int = 5
    superadmin: int = 0


# ---------------------------------------------------------------------------
# 基本限流 (check / record)
# ---------------------------------------------------------------------------


class TestRateLimiterCheck:
    def test_first_call_allowed(self) -> None:
        limiter = RateLimiter(cast(Any, _MockConfig)())
        allowed, remaining = limiter.check(1001)
        assert allowed is True
        assert remaining == 0

    def test_second_call_blocked(self) -> None:
        limiter = RateLimiter(cast(Any, _MockConfig)())
        limiter.record(1001)
        allowed, remaining = limiter.check(1001)
        assert allowed is False
        assert remaining > 0

    def test_superadmin_always_allowed(self) -> None:
        cfg = _MockConfig(superadmins={1001})
        limiter = RateLimiter(cast(Any, cfg))
        limiter.record(1001)
        allowed, _ = limiter.check(1001)
        assert allowed is True

    def test_admin_shorter_cooldown(self) -> None:
        cfg = _MockConfig(admins={2001})
        limiter = RateLimiter(cast(Any, cfg))
        # 模拟 admin 在较短冷却期后可以调用
        limiter._last_calls[2001] = time.time() - RateLimiter.ADMIN_COOLDOWN - 1
        allowed, _ = limiter.check(2001)
        assert allowed is True

    def test_normal_user_cooldown(self) -> None:
        cfg = _MockConfig()
        limiter = RateLimiter(cast(Any, cfg))
        limiter._last_calls[3001] = time.time() - RateLimiter.USER_COOLDOWN + 2
        allowed, remaining = limiter.check(3001)
        assert allowed is False
        assert remaining >= 1

    def test_cooldown_expires(self) -> None:
        cfg = _MockConfig()
        limiter = RateLimiter(cast(Any, cfg))
        limiter._last_calls[3001] = time.time() - RateLimiter.USER_COOLDOWN - 1
        allowed, _ = limiter.check(3001)
        assert allowed is True


class TestRateLimiterRecord:
    def test_record_stores_time(self) -> None:
        limiter = RateLimiter(cast(Any, _MockConfig)())
        limiter.record(1001)
        assert 1001 in limiter._last_calls

    def test_record_superadmin_skipped(self) -> None:
        cfg = _MockConfig(superadmins={1001})
        limiter = RateLimiter(cast(Any, cfg))
        limiter.record(1001)
        assert 1001 not in limiter._last_calls


# ---------------------------------------------------------------------------
# /ask 限流
# ---------------------------------------------------------------------------


class TestRateLimiterAsk:
    def test_ask_first_call_allowed(self) -> None:
        limiter = RateLimiter(cast(Any, _MockConfig)())
        allowed, _ = limiter.check_ask(1001)
        assert allowed is True

    def test_ask_blocked_within_cooldown(self) -> None:
        limiter = RateLimiter(cast(Any, _MockConfig)())
        limiter.record_ask(1001)
        allowed, remaining = limiter.check_ask(1001)
        assert allowed is False
        assert remaining > 0

    def test_ask_superadmin_bypass(self) -> None:
        cfg = _MockConfig(superadmins={1001})
        limiter = RateLimiter(cast(Any, cfg))
        limiter.record_ask(1001)
        allowed, _ = limiter.check_ask(1001)
        assert allowed is True

    def test_ask_cooldown_expires(self) -> None:
        cfg = _MockConfig()
        limiter = RateLimiter(cast(Any, cfg))
        limiter._last_ask_calls[1001] = time.time() - RateLimiter.ASK_COOLDOWN - 1
        allowed, _ = limiter.check_ask(1001)
        assert allowed is True


# ---------------------------------------------------------------------------
# /stats 限流
# ---------------------------------------------------------------------------


class TestRateLimiterStats:
    def test_stats_first_call_allowed(self) -> None:
        limiter = RateLimiter(cast(Any, _MockConfig)())
        allowed, _ = limiter.check_stats(1001)
        assert allowed is True

    def test_stats_blocked_for_normal_user(self) -> None:
        limiter = RateLimiter(cast(Any, _MockConfig)())
        limiter.record_stats(1001)
        allowed, remaining = limiter.check_stats(1001)
        assert allowed is False
        assert remaining > 0

    def test_stats_admin_bypass(self) -> None:
        cfg = _MockConfig(admins={2001})
        limiter = RateLimiter(cast(Any, cfg))
        limiter.record_stats(2001)
        allowed, _ = limiter.check_stats(2001)
        assert allowed is True

    def test_stats_superadmin_bypass(self) -> None:
        cfg = _MockConfig(superadmins={1001})
        limiter = RateLimiter(cast(Any, cfg))
        limiter.record_stats(1001)
        allowed, _ = limiter.check_stats(1001)
        assert allowed is True

    def test_stats_record_skipped_for_admin(self) -> None:
        cfg = _MockConfig(admins={2001})
        limiter = RateLimiter(cast(Any, cfg))
        limiter.record_stats(2001)
        assert 2001 not in limiter._last_stats_calls


# ---------------------------------------------------------------------------
# 动态命令限流 (check_command / record_command)
# ---------------------------------------------------------------------------


class TestRateLimiterCommand:
    def test_command_first_call_allowed(self) -> None:
        limiter = RateLimiter(cast(Any, _MockConfig)())
        limits = _MockCommandRateLimit()
        allowed, _ = limiter.check_command(1001, "test_cmd", cast(Any, limits))
        assert allowed is True

    def test_command_blocked_after_record(self) -> None:
        limiter = RateLimiter(cast(Any, _MockConfig)())
        limits = _MockCommandRateLimit(user=10)
        limiter.record_command(1001, "cmd", cast(Any, limits))
        allowed, remaining = limiter.check_command(1001, "cmd", cast(Any, limits))
        assert allowed is False
        assert remaining > 0

    def test_command_superadmin_zero_cooldown(self) -> None:
        cfg = _MockConfig(superadmins={1001})
        limiter = RateLimiter(cast(Any, cfg))
        limits = _MockCommandRateLimit(superadmin=0)
        limiter.record_command(1001, "cmd", cast(Any, limits))
        allowed, _ = limiter.check_command(1001, "cmd", cast(Any, limits))
        assert allowed is True

    def test_command_admin_shorter_cooldown(self) -> None:
        cfg = _MockConfig(admins={2001})
        limiter = RateLimiter(cast(Any, cfg))
        limits = _MockCommandRateLimit(admin=5, user=60)
        limiter._command_calls.setdefault("cmd", {})[2001] = time.time() - 6
        allowed, _ = limiter.check_command(2001, "cmd", cast(Any, limits))
        assert allowed is True

    def test_command_different_commands_independent(self) -> None:
        limiter = RateLimiter(cast(Any, _MockConfig)())
        limits = _MockCommandRateLimit(user=60)
        limiter.record_command(1001, "cmd_a", cast(Any, limits))
        allowed, _ = limiter.check_command(1001, "cmd_b", cast(Any, limits))
        assert allowed is True


# ---------------------------------------------------------------------------
# clear 方法
# ---------------------------------------------------------------------------


class TestRateLimiterClear:
    def test_clear_removes_user(self) -> None:
        limiter = RateLimiter(cast(Any, _MockConfig)())
        limiter.record(1001)
        limiter.clear(1001)
        allowed, _ = limiter.check(1001)
        assert allowed is True

    def test_clear_ask(self) -> None:
        limiter = RateLimiter(cast(Any, _MockConfig)())
        limiter.record_ask(1001)
        limiter.clear_ask(1001)
        allowed, _ = limiter.check_ask(1001)
        assert allowed is True

    def test_clear_stats(self) -> None:
        limiter = RateLimiter(cast(Any, _MockConfig)())
        limiter.record_stats(1001)
        limiter.clear_stats(1001)
        allowed, _ = limiter.check_stats(1001)
        assert allowed is True

    def test_clear_all(self) -> None:
        limiter = RateLimiter(cast(Any, _MockConfig)())
        limiter.record(1001)
        limiter.record_ask(1001)
        limiter.record_stats(1001)
        limits = _MockCommandRateLimit()
        limiter.record_command(1001, "cmd", cast(Any, limits))
        limiter.clear_all()
        assert limiter._last_calls == {}
        assert limiter._last_ask_calls == {}
        assert limiter._last_stats_calls == {}
        assert limiter._command_calls == {}

    def test_clear_nonexistent_user_no_error(self) -> None:
        limiter = RateLimiter(cast(Any, _MockConfig)())
        limiter.clear(9999)  # 不应抛出异常
        limiter.clear_ask(9999)
        limiter.clear_stats(9999)
