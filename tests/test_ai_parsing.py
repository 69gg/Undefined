"""Tests for Undefined.ai.parsing module."""

from __future__ import annotations

import pytest

from Undefined.ai.parsing import extract_choices_content


class TestExtractChoicesContent:
    """Tests for extract_choices_content()."""

    def test_standard_response(self) -> None:
        result: dict[str, object] = {
            "choices": [{"message": {"content": "Hello, world!"}}]
        }
        assert extract_choices_content(result) == "Hello, world!"

    def test_data_wrapped_response(self) -> None:
        result: dict[str, object] = {
            "data": {"choices": [{"message": {"content": "nested content"}}]}
        }
        assert extract_choices_content(result) == "nested content"

    def test_output_text_field(self) -> None:
        result: dict[str, object] = {
            "output_text": "direct output",
            "choices": [{"message": {"content": "ignored"}}],
        }
        assert extract_choices_content(result) == "direct output"

    def test_output_text_preferred_over_choices(self) -> None:
        result: dict[str, object] = {"output_text": "preferred"}
        assert extract_choices_content(result) == "preferred"

    def test_output_text_non_string_falls_through(self) -> None:
        result: dict[str, object] = {
            "output_text": 42,
            "choices": [{"message": {"content": "fallback"}}],
        }
        assert extract_choices_content(result) == "fallback"

    def test_empty_choices_raises(self) -> None:
        result: dict[str, object] = {"choices": []}
        with pytest.raises(KeyError):
            extract_choices_content(result)

    def test_no_choices_key_raises(self) -> None:
        result: dict[str, object] = {"id": "123", "object": "chat.completion"}
        with pytest.raises(KeyError):
            extract_choices_content(result)

    def test_no_content_in_message(self) -> None:
        result: dict[str, object] = {"choices": [{"message": {}}]}
        assert extract_choices_content(result) == ""

    def test_message_is_none(self) -> None:
        """message=None triggers AttributeError in tool_calls check (known bug)."""
        result: dict[str, object] = {"choices": [{"message": None}]}
        with pytest.raises(AttributeError):
            extract_choices_content(result)

    def test_choice_with_content_directly(self) -> None:
        result: dict[str, object] = {"choices": [{"content": "direct"}]}
        assert extract_choices_content(result) == "direct"

    def test_tool_calls_no_content(self) -> None:
        result: dict[str, object] = {
            "choices": [{"message": {"tool_calls": [{"function": {"name": "test"}}]}}]
        }
        assert extract_choices_content(result) == ""

    def test_refusal_field_content_still_extracted(self) -> None:
        result: dict[str, object] = {
            "choices": [
                {
                    "message": {
                        "content": "I can help with that.",
                        "refusal": None,
                    }
                }
            ]
        }
        assert extract_choices_content(result) == "I can help with that."

    def test_multiple_choices_returns_first(self) -> None:
        result: dict[str, object] = {
            "choices": [
                {"message": {"content": "first"}},
                {"message": {"content": "second"}},
            ]
        }
        assert extract_choices_content(result) == "first"

    def test_empty_dict_raises(self) -> None:
        with pytest.raises(KeyError):
            extract_choices_content({})

    def test_message_is_string(self) -> None:
        result: dict[str, object] = {"choices": [{"message": "plain string"}]}
        assert extract_choices_content(result) == "plain string"
