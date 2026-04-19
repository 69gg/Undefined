"""TokenUsage 序列化/反序列化 单元测试"""

from __future__ import annotations

from typing import Any

import pytest

from Undefined.token_usage_storage import TokenUsage


def _sample_dict() -> dict[str, Any]:
    return {
        "timestamp": "2025-01-01T00:00:00",
        "model_name": "gpt-4",
        "prompt_tokens": 100,
        "completion_tokens": 50,
        "total_tokens": 150,
        "duration_seconds": 1.5,
        "call_type": "chat",
        "success": True,
    }


# ---------------------------------------------------------------------------
# to_dict / from_dict 往返
# ---------------------------------------------------------------------------


class TestTokenUsageRoundtrip:
    def test_basic_roundtrip(self) -> None:
        d = _sample_dict()
        usage = TokenUsage.from_dict(d)
        assert usage.to_dict() == d

    def test_all_fields_preserved(self) -> None:
        usage = TokenUsage(
            timestamp="ts",
            model_name="m",
            prompt_tokens=10,
            completion_tokens=20,
            total_tokens=30,
            duration_seconds=0.5,
            call_type="agent",
            success=False,
        )
        restored = TokenUsage.from_dict(usage.to_dict())
        assert restored == usage


# ---------------------------------------------------------------------------
# from_dict — 缺失字段回退
# ---------------------------------------------------------------------------


class TestTokenUsageFromDictDefaults:
    def test_empty_dict(self) -> None:
        usage = TokenUsage.from_dict({})
        assert usage.timestamp == ""
        assert usage.model_name == ""
        assert usage.prompt_tokens == 0
        assert usage.completion_tokens == 0
        assert usage.total_tokens == 0
        assert usage.duration_seconds == 0.0
        assert usage.call_type == "unknown"
        assert usage.success is True  # 默认为 True

    def test_timestamp_fallback_to_time(self) -> None:
        usage = TokenUsage.from_dict({"time": "2025-01-01"})
        assert usage.timestamp == "2025-01-01"

    def test_timestamp_fallback_to_created_at(self) -> None:
        usage = TokenUsage.from_dict({"created_at": "2025-02-02"})
        assert usage.timestamp == "2025-02-02"

    def test_model_name_fallback_to_model(self) -> None:
        usage = TokenUsage.from_dict({"model": "claude"})
        assert usage.model_name == "claude"

    def test_prompt_tokens_fallback_to_input_tokens(self) -> None:
        usage = TokenUsage.from_dict({"input_tokens": 42})
        assert usage.prompt_tokens == 42

    def test_completion_tokens_fallback_to_output_tokens(self) -> None:
        usage = TokenUsage.from_dict({"output_tokens": 24})
        assert usage.completion_tokens == 24

    def test_total_tokens_auto_sum(self) -> None:
        usage = TokenUsage.from_dict({"prompt_tokens": 10, "completion_tokens": 20})
        assert usage.total_tokens == 30

    def test_total_tokens_explicit(self) -> None:
        usage = TokenUsage.from_dict(
            {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 99}
        )
        assert usage.total_tokens == 99

    def test_call_type_fallback_to_type(self) -> None:
        usage = TokenUsage.from_dict({"type": "vision"})
        assert usage.call_type == "vision"

    def test_duration_fallback_to_duration(self) -> None:
        usage = TokenUsage.from_dict({"duration": 3.14})
        assert usage.duration_seconds == pytest.approx(3.14)


# ---------------------------------------------------------------------------
# from_dict — success 字段各种类型
# ---------------------------------------------------------------------------


class TestTokenUsageSuccess:
    def test_success_bool_true(self) -> None:
        assert TokenUsage.from_dict({"success": True}).success is True

    def test_success_bool_false(self) -> None:
        assert TokenUsage.from_dict({"success": False}).success is False

    def test_success_string_false(self) -> None:
        assert TokenUsage.from_dict({"success": "false"}).success is False

    def test_success_string_0(self) -> None:
        assert TokenUsage.from_dict({"success": "0"}).success is False

    def test_success_string_no(self) -> None:
        assert TokenUsage.from_dict({"success": "no"}).success is False

    def test_success_string_yes(self) -> None:
        assert TokenUsage.from_dict({"success": "yes"}).success is True

    def test_success_int_1(self) -> None:
        assert TokenUsage.from_dict({"success": 1}).success is True

    def test_success_int_0(self) -> None:
        assert TokenUsage.from_dict({"success": 0}).success is False


# ---------------------------------------------------------------------------
# from_dict — 类型转换容错
# ---------------------------------------------------------------------------


class TestTokenUsageTypeCoercion:
    def test_string_tokens(self) -> None:
        usage = TokenUsage.from_dict({"prompt_tokens": "42"})
        assert usage.prompt_tokens == 42

    def test_invalid_tokens_default_zero(self) -> None:
        usage = TokenUsage.from_dict({"prompt_tokens": "abc"})
        assert usage.prompt_tokens == 0

    def test_none_tokens_default_zero(self) -> None:
        usage = TokenUsage.from_dict({"prompt_tokens": None})
        assert usage.prompt_tokens == 0

    def test_non_string_timestamp(self) -> None:
        usage = TokenUsage.from_dict({"timestamp": 12345})
        assert usage.timestamp == "12345"

    def test_non_string_model_name(self) -> None:
        usage = TokenUsage.from_dict({"model_name": 42})
        assert usage.model_name == "42"

    def test_extra_fields_ignored(self) -> None:
        d = _sample_dict()
        d["extra_field"] = "ignored"
        d["another"] = 999
        usage = TokenUsage.from_dict(d)
        assert usage.model_name == "gpt-4"
