"""Tests for Undefined.ai.queue_budget module."""

from __future__ import annotations

from types import SimpleNamespace

from Undefined.ai.queue_budget import (
    DEFAULT_QUEUED_LLM_ATTEMPT_TIMEOUT_SECONDS,
    QUEUED_LLM_TIMEOUT_GRACE_SECONDS,
    compute_queued_llm_timeout_seconds,
    resolve_effective_retry_count,
)


class TestResolveEffectiveRetryCount:
    """Tests for resolve_effective_retry_count()."""

    def test_from_runtime_config(self) -> None:
        cfg = SimpleNamespace(ai_request_max_retries=3)
        assert resolve_effective_retry_count(cfg) == 3

    def test_from_queue_manager(self) -> None:
        cfg = SimpleNamespace(ai_request_max_retries=5)
        qm = SimpleNamespace(get_max_retries=lambda: 2)
        assert resolve_effective_retry_count(cfg, qm) == 2

    def test_queue_manager_takes_precedence(self) -> None:
        cfg = SimpleNamespace(ai_request_max_retries=10)
        qm = SimpleNamespace(get_max_retries=lambda: 1)
        assert resolve_effective_retry_count(cfg, qm) == 1

    def test_negative_retries_clamped_to_zero(self) -> None:
        cfg = SimpleNamespace(ai_request_max_retries=-5)
        assert resolve_effective_retry_count(cfg) == 0

    def test_none_retries_returns_zero(self) -> None:
        cfg = SimpleNamespace(ai_request_max_retries=None)
        assert resolve_effective_retry_count(cfg) == 0

    def test_missing_attribute_returns_zero(self) -> None:
        cfg = SimpleNamespace()
        assert resolve_effective_retry_count(cfg) == 0

    def test_queue_manager_invalid_return(self) -> None:
        cfg = SimpleNamespace(ai_request_max_retries=3)
        qm = SimpleNamespace(get_max_retries=lambda: "invalid")
        assert resolve_effective_retry_count(cfg, qm) == 0

    def test_queue_manager_negative_clamped(self) -> None:
        cfg = SimpleNamespace(ai_request_max_retries=3)
        qm = SimpleNamespace(get_max_retries=lambda: -1)
        assert resolve_effective_retry_count(cfg, qm) == 0

    def test_queue_manager_none_no_get_max_retries(self) -> None:
        cfg = SimpleNamespace(ai_request_max_retries=4)
        qm = SimpleNamespace()
        assert resolve_effective_retry_count(cfg, qm) == 4

    def test_zero_retries(self) -> None:
        cfg = SimpleNamespace(ai_request_max_retries=0)
        assert resolve_effective_retry_count(cfg) == 0


class TestComputeQueuedLlmTimeoutSeconds:
    """Tests for compute_queued_llm_timeout_seconds()."""

    def _make_model_config(
        self,
        interval: float = 0.0,
        pool_enabled: bool = False,
        pool_models: list[SimpleNamespace] | None = None,
    ) -> SimpleNamespace:
        pool = SimpleNamespace(
            enabled=pool_enabled,
            models=pool_models or [],
        )
        return SimpleNamespace(queue_interval_seconds=interval, pool=pool)

    def test_defaults_zero_retries(self) -> None:
        cfg = SimpleNamespace(ai_request_max_retries=0)
        model_cfg = self._make_model_config()
        result = compute_queued_llm_timeout_seconds(cfg, model_cfg)
        expected = (
            0.0
            + DEFAULT_QUEUED_LLM_ATTEMPT_TIMEOUT_SECONDS * 1
            + 0.0 * 1
            + QUEUED_LLM_TIMEOUT_GRACE_SECONDS
        )
        assert result == expected

    def test_with_retries(self) -> None:
        cfg = SimpleNamespace(ai_request_max_retries=2)
        model_cfg = self._make_model_config(interval=1.0)
        result = compute_queued_llm_timeout_seconds(cfg, model_cfg)
        # attempts=3, dispatch_intervals=3 (2 retries + 1 first)
        expected = (
            0.0
            + DEFAULT_QUEUED_LLM_ATTEMPT_TIMEOUT_SECONDS * 3
            + 1.0 * 3
            + QUEUED_LLM_TIMEOUT_GRACE_SECONDS
        )
        assert result == expected

    def test_explicit_retry_count(self) -> None:
        cfg = SimpleNamespace(ai_request_max_retries=99)
        model_cfg = self._make_model_config()
        result = compute_queued_llm_timeout_seconds(cfg, model_cfg, retry_count=1)
        # explicit retry_count=1 overrides config
        expected = (
            0.0
            + DEFAULT_QUEUED_LLM_ATTEMPT_TIMEOUT_SECONDS * 2
            + 0.0 * 2
            + QUEUED_LLM_TIMEOUT_GRACE_SECONDS
        )
        assert result == expected

    def test_initial_wait(self) -> None:
        cfg = SimpleNamespace(ai_request_max_retries=0)
        model_cfg = self._make_model_config()
        result = compute_queued_llm_timeout_seconds(
            cfg, model_cfg, initial_wait_seconds=10.0
        )
        expected = (
            10.0
            + DEFAULT_QUEUED_LLM_ATTEMPT_TIMEOUT_SECONDS * 1
            + 0.0 * 1
            + QUEUED_LLM_TIMEOUT_GRACE_SECONDS
        )
        assert result == expected

    def test_no_first_dispatch_interval(self) -> None:
        cfg = SimpleNamespace(ai_request_max_retries=2)
        model_cfg = self._make_model_config(interval=5.0)
        result = compute_queued_llm_timeout_seconds(
            cfg, model_cfg, include_first_dispatch_interval=False
        )
        # dispatch_intervals = retries only = 2
        expected = (
            0.0
            + DEFAULT_QUEUED_LLM_ATTEMPT_TIMEOUT_SECONDS * 3
            + 5.0 * 2
            + QUEUED_LLM_TIMEOUT_GRACE_SECONDS
        )
        assert result == expected

    def test_custom_attempt_timeout(self) -> None:
        cfg = SimpleNamespace(ai_request_max_retries=0)
        model_cfg = self._make_model_config()
        result = compute_queued_llm_timeout_seconds(
            cfg, model_cfg, attempt_timeout_seconds=60.0
        )
        expected = 0.0 + 60.0 * 1 + 0.0 * 1 + QUEUED_LLM_TIMEOUT_GRACE_SECONDS
        assert result == expected

    def test_custom_grace_seconds(self) -> None:
        cfg = SimpleNamespace(ai_request_max_retries=0)
        model_cfg = self._make_model_config()
        result = compute_queued_llm_timeout_seconds(cfg, model_cfg, grace_seconds=100.0)
        expected = (
            0.0 + DEFAULT_QUEUED_LLM_ATTEMPT_TIMEOUT_SECONDS * 1 + 0.0 * 1 + 100.0
        )
        assert result == expected

    def test_pool_models_max_interval(self) -> None:
        pool_models = [
            SimpleNamespace(queue_interval_seconds=2.0),
            SimpleNamespace(queue_interval_seconds=5.0),
            SimpleNamespace(queue_interval_seconds=1.0),
        ]
        cfg = SimpleNamespace(ai_request_max_retries=1)
        model_cfg = self._make_model_config(
            interval=3.0, pool_enabled=True, pool_models=pool_models
        )
        result = compute_queued_llm_timeout_seconds(cfg, model_cfg)
        # max interval = max(3.0, 2.0, 5.0, 1.0) = 5.0
        # attempts=2, dispatch=2
        expected = (
            0.0
            + DEFAULT_QUEUED_LLM_ATTEMPT_TIMEOUT_SECONDS * 2
            + 5.0 * 2
            + QUEUED_LLM_TIMEOUT_GRACE_SECONDS
        )
        assert result == expected

    def test_pool_disabled_ignores_pool_models(self) -> None:
        pool_models = [SimpleNamespace(queue_interval_seconds=100.0)]
        cfg = SimpleNamespace(ai_request_max_retries=0)
        model_cfg = self._make_model_config(
            interval=1.0, pool_enabled=False, pool_models=pool_models
        )
        result = compute_queued_llm_timeout_seconds(cfg, model_cfg)
        # pool disabled: only base interval=1.0
        expected = (
            0.0
            + DEFAULT_QUEUED_LLM_ATTEMPT_TIMEOUT_SECONDS * 1
            + 1.0 * 1
            + QUEUED_LLM_TIMEOUT_GRACE_SECONDS
        )
        assert result == expected

    def test_negative_retry_count_clamped(self) -> None:
        cfg = SimpleNamespace(ai_request_max_retries=0)
        model_cfg = self._make_model_config()
        result = compute_queued_llm_timeout_seconds(cfg, model_cfg, retry_count=-5)
        # clamped to 0 → 1 attempt
        expected = (
            0.0
            + DEFAULT_QUEUED_LLM_ATTEMPT_TIMEOUT_SECONDS * 1
            + 0.0 * 1
            + QUEUED_LLM_TIMEOUT_GRACE_SECONDS
        )
        assert result == expected
