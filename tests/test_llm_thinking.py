"""Tests for Undefined.ai.llm.thinking — thinking extraction and normalization."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

from Undefined.ai.llm.thinking import (
    _is_deepseek_provider,
    extract_thinking_content,
    normalize_thinking_override,
    stringify_thinking,
)


# ---------------------------------------------------------------------------
# stringify_thinking
# ---------------------------------------------------------------------------


class TestStringifyThinking:
    def test_none_returns_empty(self) -> None:
        assert stringify_thinking(None) == ""

    def test_string_returned_as_is(self) -> None:
        assert stringify_thinking("my thoughts") == "my thoughts"

    def test_empty_string_returned(self) -> None:
        assert stringify_thinking("") == ""

    def test_list_of_strings_joined_with_newline(self) -> None:
        result = stringify_thinking(["step 1", "step 2"])
        assert "step 1" in result
        assert "step 2" in result

    def test_list_with_empty_strings_filtered(self) -> None:
        result = stringify_thinking(["a", "", "b"])
        assert result == "a\nb"

    def test_list_with_none_filtered(self) -> None:
        result = stringify_thinking([None, "a", None])
        assert "a" in result

    def test_dict_with_content_key(self) -> None:
        assert stringify_thinking({"content": "reasoning here"}) == "reasoning here"

    def test_dict_without_content_key_stringified(self) -> None:
        result = stringify_thinking({"other": "data"})
        # Falls back to str(value)
        assert "other" in result or "data" in result

    def test_dict_with_empty_content_falls_back(self) -> None:
        result = stringify_thinking({"content": ""})
        # Empty content → str(dict)
        assert isinstance(result, str)

    def test_integer_converted_to_string(self) -> None:
        assert stringify_thinking(42) == "42"

    def test_nested_list_of_dicts(self) -> None:
        value = [{"content": "thought 1"}, {"content": "thought 2"}]
        result = stringify_thinking(value)
        assert "thought 1" in result
        assert "thought 2" in result


# ---------------------------------------------------------------------------
# extract_thinking_content
# ---------------------------------------------------------------------------


class TestExtractThinkingContent:
    def test_extracts_from_choices_message_reasoning_content(self) -> None:
        result = {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "hi",
                        "reasoning_content": "my reasoning",
                    }
                }
            ]
        }
        assert extract_thinking_content(result) == "my reasoning"

    def test_extracts_thinking_key_from_message(self) -> None:
        result = {
            "choices": [{"message": {"role": "assistant", "thinking": "deep thoughts"}}]
        }
        assert extract_thinking_content(result) == "deep thoughts"

    def test_extracts_from_choice_directly_when_no_message(self) -> None:
        result = {"choices": [{"reasoning_content": "direct reasoning"}]}
        assert extract_thinking_content(result) == "direct reasoning"

    def test_extracts_from_result_root(self) -> None:
        result = {"output": "text", "thinking": "top-level thinking"}
        assert extract_thinking_content(result) == "top-level thinking"

    def test_no_thinking_returns_empty(self) -> None:
        result = {"choices": [{"message": {"role": "assistant", "content": "hi"}}]}
        assert extract_thinking_content(result) == ""

    def test_empty_choices_returns_empty(self) -> None:
        result: dict[str, Any] = {"choices": []}
        assert extract_thinking_content(result) == ""

    def test_no_choices_key_falls_back_to_root(self) -> None:
        result = {"chain_of_thought": "cot content"}
        assert extract_thinking_content(result) == "cot content"

    def test_all_thinking_keys_supported(self) -> None:
        thinking_keys = (
            "thinking",
            "reasoning",
            "reasoning_content",
            "chain_of_thought",
            "cot",
            "thoughts",
        )
        for key in thinking_keys:
            result = {"choices": [{"message": {key: f"value for {key}"}}]}
            extracted = extract_thinking_content(result)
            assert extracted == f"value for {key}", f"Failed for key {key!r}"


# ---------------------------------------------------------------------------
# _is_deepseek_provider
# ---------------------------------------------------------------------------


class TestIsDeepseekProvider:
    def test_deepseek_model_name_prefix(self) -> None:
        config = SimpleNamespace(
            model_name="deepseek-r1", api_url="https://api.openai.com/v1"
        )
        assert _is_deepseek_provider(cast(Any, config)) is True

    def test_deepseek_in_api_url(self) -> None:
        config = SimpleNamespace(
            model_name="some-model", api_url="https://api.deepseek.com/v1"
        )
        assert _is_deepseek_provider(cast(Any, config)) is True

    def test_non_deepseek_returns_false(self) -> None:
        config = SimpleNamespace(
            model_name="gpt-4o", api_url="https://api.openai.com/v1"
        )
        assert _is_deepseek_provider(cast(Any, config)) is False

    def test_deepseek_in_model_name_uppercase(self) -> None:
        config = SimpleNamespace(
            model_name="DeepSeek-V3", api_url="https://other.com/v1"
        )
        assert _is_deepseek_provider(cast(Any, config)) is True

    def test_missing_attributes_returns_false(self) -> None:
        config = SimpleNamespace()
        assert _is_deepseek_provider(cast(Any, config)) is False


# ---------------------------------------------------------------------------
# normalize_thinking_override
# ---------------------------------------------------------------------------


class TestNormalizeThinkingOverride:
    def _non_deepseek_config(self) -> Any:
        return SimpleNamespace(model_name="gpt-4o", api_url="https://api.openai.com/v1")

    def _deepseek_config(self) -> Any:
        return SimpleNamespace(
            model_name="deepseek-r1", api_url="https://api.deepseek.com/v1"
        )

    def test_none_returns_none(self) -> None:
        assert normalize_thinking_override(None, self._non_deepseek_config()) is None

    def test_bool_true_returns_enabled(self) -> None:
        result = normalize_thinking_override(True, self._non_deepseek_config())
        assert result == {"type": "enabled"}

    def test_bool_false_returns_disabled(self) -> None:
        result = normalize_thinking_override(False, self._non_deepseek_config())
        assert result == {"type": "disabled"}

    def test_string_enabled(self) -> None:
        result = normalize_thinking_override("enabled", self._non_deepseek_config())
        assert result == {"type": "enabled"}

    def test_string_disabled(self) -> None:
        result = normalize_thinking_override("disabled", self._non_deepseek_config())
        assert result == {"type": "disabled"}

    def test_string_invalid_returns_none(self) -> None:
        result = normalize_thinking_override("maybe", self._non_deepseek_config())
        assert result is None

    def test_dict_with_type_enabled_non_deepseek(self) -> None:
        value = {"type": "enabled", "budget_tokens": 1000}
        result = normalize_thinking_override(value, self._non_deepseek_config())
        assert result is not None
        assert result["type"] == "enabled"
        # Non-deepseek keeps extra fields
        assert "budget_tokens" in result

    def test_dict_with_type_enabled_deepseek_strips_extra(self) -> None:
        value = {"type": "enabled", "budget_tokens": 1000}
        result = normalize_thinking_override(value, self._deepseek_config())
        assert result == {"type": "enabled"}

    def test_dict_with_enabled_bool_true_non_deepseek(self) -> None:
        value = {"enabled": True, "budget_tokens": 500}
        result = normalize_thinking_override(value, self._non_deepseek_config())
        assert result is not None
        assert result["type"] == "enabled"
        # Non-deepseek keeps extra fields except 'enabled'
        assert "budget_tokens" in result
        assert "enabled" not in result

    def test_dict_with_enabled_bool_false_deepseek(self) -> None:
        value = {"enabled": False}
        result = normalize_thinking_override(value, self._deepseek_config())
        assert result == {"type": "disabled"}

    def test_dict_without_type_or_enabled_returns_none(self) -> None:
        value = {"budget_tokens": 500}
        result = normalize_thinking_override(value, self._non_deepseek_config())
        assert result is None

    def test_type_value_case_insensitive(self) -> None:
        value = {"type": "ENABLED"}
        result = normalize_thinking_override(value, self._non_deepseek_config())
        assert result is not None
        assert result["type"] == "enabled"
