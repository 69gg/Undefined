"""Tests for Undefined.utils.tool_calls."""

from __future__ import annotations

import json
import logging
from typing import Any

import pytest

from Undefined.utils.tool_calls import (
    TextToolCallParseError,
    _clean_json_string,
    _repair_json_like_string,
    _strip_code_fences,
    extract_required_tool_call_arguments,
    normalize_tool_arguments_json,
    parse_text_tool_calls,
    parse_tool_arguments,
)


@pytest.fixture()
def test_logger() -> logging.Logger:
    return logging.getLogger("test")


# ---------------------------------------------------------------------------
# _strip_code_fences
# ---------------------------------------------------------------------------


class TestStripCodeFences:
    def test_strip_json_fence(self) -> None:
        raw = '```json\n{"a": 1}\n```'
        assert _strip_code_fences(raw) == '{"a": 1}'

    def test_strip_generic_fence(self) -> None:
        raw = '```\n{"a": 1}\n```'
        assert _strip_code_fences(raw) == '{"a": 1}'

    def test_no_fence(self) -> None:
        raw = '{"a": 1}'
        assert _strip_code_fences(raw) == '{"a": 1}'


# ---------------------------------------------------------------------------
# _clean_json_string
# ---------------------------------------------------------------------------


class TestCleanJsonString:
    def test_removes_control_chars(self) -> None:
        raw = '{"key":\r\n\t"val"}'
        result = _clean_json_string(raw)
        assert "\r" not in result
        assert "\n" not in result
        assert "\t" not in result


# ---------------------------------------------------------------------------
# _repair_json_like_string
# ---------------------------------------------------------------------------


class TestRepairJsonLikeString:
    def test_missing_closing_brace(self) -> None:
        raw = '{"a": 1'
        repaired = _repair_json_like_string(raw)
        assert json.loads(repaired) == {"a": 1}

    def test_trailing_comma(self) -> None:
        raw = '{"a": 1, '
        repaired = _repair_json_like_string(raw)
        assert json.loads(repaired) == {"a": 1}

    def test_empty_string(self) -> None:
        assert _repair_json_like_string("") == ""


# ---------------------------------------------------------------------------
# parse_tool_arguments
# ---------------------------------------------------------------------------


class TestParseToolArguments:
    def test_dict_passthrough(self) -> None:
        d: dict[str, Any] = {"key": "val"}
        assert parse_tool_arguments(d) is d

    def test_none_returns_empty(self) -> None:
        assert parse_tool_arguments(None) == {}

    def test_empty_string_returns_empty(self) -> None:
        assert parse_tool_arguments("") == {}

    def test_whitespace_returns_empty(self) -> None:
        assert parse_tool_arguments("   ") == {}

    def test_valid_json_string(self) -> None:
        result = parse_tool_arguments('{"x": 42}')
        assert result == {"x": 42}

    def test_json_with_code_fences(self) -> None:
        raw = '```json\n{"x": 42}\n```'
        assert parse_tool_arguments(raw) == {"x": 42}

    def test_json_with_control_chars(self, test_logger: logging.Logger) -> None:
        raw = '{"x":\r\n42}'
        result = parse_tool_arguments(raw, logger=test_logger, tool_name="t")
        assert result == {"x": 42}

    def test_truncated_json_repaired(self, test_logger: logging.Logger) -> None:
        raw = '{"a": "hello"'
        result = parse_tool_arguments(raw, logger=test_logger, tool_name="t")
        assert result == {"a": "hello"}

    def test_json_with_trailing_content(self, test_logger: logging.Logger) -> None:
        raw = '{"a": 1} some trailing text'
        result = parse_tool_arguments(raw, logger=test_logger, tool_name="t")
        assert result == {"a": 1}

    def test_non_dict_json_returns_empty(self, test_logger: logging.Logger) -> None:
        raw = "[1, 2, 3]"
        result = parse_tool_arguments(raw, logger=test_logger, tool_name="t")
        assert result == {}

    def test_completely_invalid_returns_empty(
        self, test_logger: logging.Logger
    ) -> None:
        raw = "this is not json at all"
        result = parse_tool_arguments(raw, logger=test_logger, tool_name="t")
        assert result == {}

    def test_unsupported_type_returns_empty(self, test_logger: logging.Logger) -> None:
        result = parse_tool_arguments(42, logger=test_logger, tool_name="t")
        assert result == {}


# ---------------------------------------------------------------------------
# parse_text_tool_calls
# ---------------------------------------------------------------------------


class TestParseTextToolCalls:
    @staticmethod
    def _names(tool_calls: list[dict[str, Any]]) -> list[str]:
        return [str(tool_call["function"]["name"]) for tool_call in tool_calls]

    @staticmethod
    def _arguments(tool_call: dict[str, Any]) -> dict[str, Any]:
        parsed = json.loads(str(tool_call["function"]["arguments"]))
        assert isinstance(parsed, dict)
        return parsed

    def test_single_json_envelope(self) -> None:
        tool_calls = parse_text_tool_calls(
            '{"tool":"end","arguments":{"memo":"静默处理","observations":[]}}'
        )

        assert self._names(tool_calls) == ["end"]
        assert self._arguments(tool_calls[0]) == {
            "memo": "静默处理",
            "observations": [],
        }
        assert tool_calls[0]["type"] == "function"
        assert str(tool_calls[0]["id"]).startswith("call_txt_")

    def test_consecutive_json_envelopes_preserve_order(self) -> None:
        tool_calls = parse_text_tool_calls(
            '{"tool":"send_message","arguments":{"message":"在做了"}}\n'
            '{"tool":"end","arguments":{"memo":"已回应","observations":[]}}'
        )

        assert self._names(tool_calls) == ["send_message", "end"]
        assert self._arguments(tool_calls[0]) == {"message": "在做了"}
        assert len({str(tool_call["id"]) for tool_call in tool_calls}) == 2

    def test_consecutive_named_json_envelopes_preserve_parallel_calls(self) -> None:
        tool_calls = parse_text_tool_calls(
            '{"name":"music.search_songs","arguments":'
            '{"query":"君往何处 m2u","limit":5}}\n'
            '{"name":"end","arguments":'
            '{"memo":"搜索 m2u 的《君往何处》","observations":[]}}'
        )

        assert self._names(tool_calls) == ["music.search_songs", "end"]
        assert self._arguments(tool_calls[0]) == {
            "query": "君往何处 m2u",
            "limit": 5,
        }
        assert self._arguments(tool_calls[1]) == {
            "memo": "搜索 m2u 的《君往何处》",
            "observations": [],
        }
        assert len({str(tool_call["id"]) for tool_call in tool_calls}) == 2

    def test_json_envelope_styles_can_be_mixed(self) -> None:
        tool_calls = parse_text_tool_calls(
            '{"tool":"first","arguments":{}}\n{"name":"second","arguments":{"value":2}}'
        )

        assert self._names(tool_calls) == ["first", "second"]
        assert self._arguments(tool_calls[1]) == {"value": 2}

    def test_json_envelope_accepts_encoded_arguments_object(self) -> None:
        tool_calls = parse_text_tool_calls(
            '{"tool":"send_message","arguments":"{\\"message\\":\\"在做了\\"}"}'
        )

        assert self._names(tool_calls) == ["send_message"]
        assert self._arguments(tool_calls[0]) == {"message": "在做了"}

    def test_escaped_parameters_attribute_and_paired_tag(self) -> None:
        raw = (
            r'<tool name="end" parameters="{\"force\": false, '
            r'\"memo\": \"静默处理\", \"observations\": []}"></tool>'
        )

        tool_calls = parse_text_tool_calls(raw)

        assert self._names(tool_calls) == ["end"]
        assert self._arguments(tool_calls[0]) == {
            "force": False,
            "memo": "静默处理",
            "observations": [],
        }

    def test_multiple_self_closing_params_tags(self) -> None:
        raw = """<tool name="send_message" params='{"message": "在做了在做了"}' />
<tool name="end" params='{"memo": "回应重试请求", "observations": ["一条观察"]}' />"""

        tool_calls = parse_text_tool_calls(raw)

        assert self._names(tool_calls) == ["send_message", "end"]
        assert self._arguments(tool_calls[0]) == {"message": "在做了在做了"}
        assert self._arguments(tool_calls[1]) == {
            "memo": "回应重试请求",
            "observations": ["一条观察"],
        }

    def test_arguments_attribute_alias(self) -> None:
        tool_calls = parse_text_tool_calls("<tool name='end' arguments='{}' />")

        assert self._names(tool_calls) == ["end"]
        assert self._arguments(tool_calls[0]) == {}

    def test_tool_execution_envelope(self) -> None:
        raw = """<tool_execution>
<tool_call name="music-_-search_songs" arguments='{"query": "克罗地亚狂想曲 Maksim", "limit": 10}'>
</tool_call>
</tool_execution>"""

        tool_calls = parse_text_tool_calls(raw)

        assert self._names(tool_calls) == ["music-_-search_songs"]
        assert self._arguments(tool_calls[0]) == {
            "query": "克罗地亚狂想曲 Maksim",
            "limit": 10,
        }
        assert str(tool_calls[0]["id"]).startswith("call_txt_")

    def test_tool_execution_accepts_multiple_and_self_closing_calls(self) -> None:
        raw = r"""```text
<tool_execution >
  <tool_call name='first' />
  <tool_call name="second" arguments="{\"value\": 2}"></tool_call>
</tool_execution>
```"""

        tool_calls = parse_text_tool_calls(raw)

        assert self._names(tool_calls) == ["first", "second"]
        assert self._arguments(tool_calls[0]) == {}
        assert self._arguments(tool_calls[1]) == {"value": 2}
        assert len({str(tool_call["id"]) for tool_call in tool_calls}) == 2

    def test_json_code_fence_is_accepted(self) -> None:
        tool_calls = parse_text_tool_calls(
            '```json\n{"tool":"end","arguments":{}}\n```'
        )

        assert self._names(tool_calls) == ["end"]

    @pytest.mark.parametrize(
        "raw",
        [
            '{"message":"普通 JSON"}',
            '{"name":"普通 JSON"}',
            "一段普通回复",
        ],
    )
    def test_ordinary_text_is_not_treated_as_tool_protocol(self, raw: str) -> None:
        assert parse_text_tool_calls(raw) == []

    @pytest.mark.parametrize(
        "raw",
        [
            '{"tool":"end","arguments":{}} trailing',
            '普通文本 {"tool":"end","arguments":{}}',
            '{"tool":"end","arguments":[],"extra":true}',
            '{"name":"end","arguments":[],"extra":true}',
            '<tool name="end" params="[]" />',
            '<tool name="end" params="{}" /> trailing',
            '普通文本 <tool name="end" params="{}" />',
            "<tool_execution></tool_execution>",
            '<tool_execution mode="parallel"></tool_execution>',
            '<tool_execution><tool_call name="end" extra="x" /></tool_execution>',
            '<tool_execution><tool_call name="end" name="again" /></tool_execution>',
            '<tool_execution><tool_call name="end" arguments="[]" /></tool_execution>',
            '<tool_execution><tool_call name="end">text</tool_call></tool_execution>',
            '<tool_call name="end" arguments="{}"></tool_call>',
            '<tool_execution><tool_call name="end" /></tool_execution> trailing',
            '普通文本 <tool_execution><tool_call name="end" /></tool_execution>',
        ],
    )
    def test_invalid_tool_protocol_is_rejected(self, raw: str) -> None:
        with pytest.raises(TextToolCallParseError):
            parse_text_tool_calls(raw)


# ---------------------------------------------------------------------------
# normalize_tool_arguments_json
# ---------------------------------------------------------------------------


class TestNormalizeToolArgumentsJson:
    def test_none(self) -> None:
        assert normalize_tool_arguments_json(None) == "{}"

    def test_dict(self) -> None:
        result = normalize_tool_arguments_json({"a": 1})
        parsed = json.loads(result)
        assert parsed == {"a": 1}

    def test_empty_string(self) -> None:
        assert normalize_tool_arguments_json("") == "{}"

    def test_valid_json_object_string(self) -> None:
        result = normalize_tool_arguments_json('{"key": "val"}')
        parsed = json.loads(result)
        assert parsed == {"key": "val"}

    def test_non_object_json_wrapped(self) -> None:
        result = normalize_tool_arguments_json("[1,2,3]")
        parsed = json.loads(result)
        assert parsed == {"_value": [1, 2, 3]}

    def test_invalid_json_wrapped_raw(self) -> None:
        result = normalize_tool_arguments_json("not json")
        parsed = json.loads(result)
        assert parsed == {"_raw": "not json"}

    def test_non_string_non_dict_wrapped(self) -> None:
        result = normalize_tool_arguments_json(42)
        parsed = json.loads(result)
        assert parsed == {"_value": 42}

    def test_number_json_string_wrapped(self) -> None:
        result = normalize_tool_arguments_json("123")
        parsed = json.loads(result)
        assert parsed == {"_value": 123}


# ---------------------------------------------------------------------------
# extract_required_tool_call_arguments
# ---------------------------------------------------------------------------


class TestExtractRequiredToolCallArguments:
    def _build_response(
        self,
        name: str = "my_tool",
        arguments: Any = '{"x": 1}',
    ) -> dict[str, Any]:
        return {
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {
                                "function": {
                                    "name": name,
                                    "arguments": arguments,
                                }
                            }
                        ]
                    }
                }
            ]
        }

    def test_happy_path(self) -> None:
        resp = self._build_response()
        result = extract_required_tool_call_arguments(
            resp, expected_tool_name="my_tool", stage="test"
        )
        assert result == {"x": 1}

    def test_missing_choices_raises(self) -> None:
        with pytest.raises(ValueError, match="choices"):
            extract_required_tool_call_arguments({}, expected_tool_name="t", stage="s")

    def test_non_dict_choice_raises(self) -> None:
        with pytest.raises(ValueError, match="choice"):
            extract_required_tool_call_arguments(
                {"choices": ["bad"]}, expected_tool_name="t", stage="s"
            )

    def test_missing_message_raises(self) -> None:
        with pytest.raises(ValueError, match="message"):
            extract_required_tool_call_arguments(
                {"choices": [{"no_message": True}]},
                expected_tool_name="t",
                stage="s",
            )

    def test_missing_tool_calls_raises(self) -> None:
        with pytest.raises(ValueError, match="tool_calls"):
            extract_required_tool_call_arguments(
                {"choices": [{"message": {"content": "hi"}}]},
                expected_tool_name="t",
                stage="s",
            )

    def test_non_dict_tool_call_raises(self) -> None:
        with pytest.raises(ValueError, match="tool_call"):
            extract_required_tool_call_arguments(
                {"choices": [{"message": {"tool_calls": ["bad"]}}]},
                expected_tool_name="t",
                stage="s",
            )

    def test_missing_function_raises(self) -> None:
        with pytest.raises(ValueError, match="function"):
            extract_required_tool_call_arguments(
                {"choices": [{"message": {"tool_calls": [{"id": "1"}]}}]},
                expected_tool_name="t",
                stage="s",
            )

    def test_name_mismatch_raises(self) -> None:
        resp = self._build_response(name="wrong_name")
        with pytest.raises(ValueError, match="不匹配"):
            extract_required_tool_call_arguments(
                resp, expected_tool_name="my_tool", stage="s"
            )

    def test_with_logger(self, test_logger: logging.Logger) -> None:
        resp = self._build_response()
        result = extract_required_tool_call_arguments(
            resp,
            expected_tool_name="my_tool",
            stage="test",
            logger=test_logger,
        )
        assert result == {"x": 1}
