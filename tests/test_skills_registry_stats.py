"""Tests for Undefined.skills.registry.SkillStats dataclass."""

from __future__ import annotations

from Undefined.skills.registry import SkillStats


class TestSkillStats:
    """Tests for SkillStats dataclass."""

    def test_initial_state(self) -> None:
        stats = SkillStats()
        assert stats.count == 0
        assert stats.success == 0
        assert stats.failure == 0
        assert stats.total_duration == 0.0
        assert stats.last_duration == 0.0
        assert stats.last_error is None
        assert stats.last_called_at is None

    def test_record_success(self) -> None:
        stats = SkillStats()
        stats.record_success(1.5)
        assert stats.count == 1
        assert stats.success == 1
        assert stats.failure == 0
        assert stats.total_duration == 1.5
        assert stats.last_duration == 1.5
        assert stats.last_error is None
        assert stats.last_called_at is not None

    def test_record_failure(self) -> None:
        stats = SkillStats()
        stats.record_failure(2.0, "timeout")
        assert stats.count == 1
        assert stats.success == 0
        assert stats.failure == 1
        assert stats.total_duration == 2.0
        assert stats.last_duration == 2.0
        assert stats.last_error == "timeout"
        assert stats.last_called_at is not None

    def test_multiple_successes(self) -> None:
        stats = SkillStats()
        stats.record_success(1.0)
        stats.record_success(2.0)
        stats.record_success(3.0)
        assert stats.count == 3
        assert stats.success == 3
        assert stats.failure == 0
        assert stats.total_duration == 6.0
        assert stats.last_duration == 3.0

    def test_mixed_success_and_failure(self) -> None:
        stats = SkillStats()
        stats.record_success(1.0)
        stats.record_failure(0.5, "error A")
        stats.record_success(2.0)
        assert stats.count == 3
        assert stats.success == 2
        assert stats.failure == 1
        assert stats.total_duration == 3.5
        assert stats.last_duration == 2.0
        assert stats.last_error is None  # cleared by success

    def test_success_clears_last_error(self) -> None:
        stats = SkillStats()
        stats.record_failure(1.0, "something broke")
        assert stats.last_error == "something broke"
        stats.record_success(0.5)
        assert stats.last_error is None

    def test_failure_overwrites_last_error(self) -> None:
        stats = SkillStats()
        stats.record_failure(1.0, "error 1")
        stats.record_failure(2.0, "error 2")
        assert stats.last_error == "error 2"

    def test_average_duration(self) -> None:
        stats = SkillStats()
        stats.record_success(2.0)
        stats.record_success(4.0)
        avg = stats.total_duration / stats.count
        assert avg == 3.0

    def test_last_called_at_updates(self) -> None:
        stats = SkillStats()
        stats.record_success(1.0)
        first_called = stats.last_called_at
        assert first_called is not None
        stats.record_failure(1.0, "err")
        assert stats.last_called_at is not None
        assert stats.last_called_at >= first_called

    def test_zero_duration(self) -> None:
        stats = SkillStats()
        stats.record_success(0.0)
        assert stats.total_duration == 0.0
        assert stats.last_duration == 0.0
        assert stats.count == 1
