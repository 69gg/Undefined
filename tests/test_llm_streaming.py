"""Tests for Undefined.ai.llm.streaming — stream aggregation and utility functions."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from openai import APIStatusError

from Undefined.ai.llm.streaming import (
    aggregate_chat_completions_stream,
    aggregate_responses_stream,
    ensure_chat_stream_usage_options,
    ensure_tool_call_slot,
    extract_stream_response_item,
    extract_stream_usage,
    merge_tool_call_delta,
    should_fallback_from_stream,
    split_chat_completion_params,
    split_responses_params,
    stringify_stream_delta,
    without_stream_request_fields,
)


# ---------------------------------------------------------------------------
# split_chat_completion_params
# ---------------------------------------------------------------------------


class TestSplitChatCompletionParams:
    def test_known_fields_go_to_known_dict(self) -> None:
        body = {"model": "gpt-4", "temperature": 0.7, "max_tokens": 100}
        known, extra = split_chat_completion_params(body)
        assert known["model"] == "gpt-4"
        assert known["temperature"] == 0.7
        assert known["max_tokens"] == 100
        assert extra == {}

    def test_unknown_fields_go_to_extra(self) -> None:
        body = {"model": "gpt-4", "custom_param": "value", "another": 123}
        known, extra = split_chat_completion_params(body)
        assert "model" in known
        assert "custom_param" in extra
        assert "another" in extra

    def test_empty_body(self) -> None:
        known, extra = split_chat_completion_params({})
        assert known == {}
        assert extra == {}

    def test_tools_and_tool_choice_are_known(self) -> None:
        body = {"tools": [{"type": "function"}], "tool_choice": "auto"}
        known, extra = split_chat_completion_params(body)
        assert "tools" in known
        assert "tool_choice" in known


# ---------------------------------------------------------------------------
# split_responses_params
# ---------------------------------------------------------------------------


class TestSplitResponsesParams:
    def test_known_responses_field_goes_to_known(self) -> None:
        body = {"model": "gpt-4", "instructions": "Be helpful", "custom": "val"}
        known, extra = split_responses_params(body)
        assert "model" in known
        assert "instructions" in known
        assert "custom" in extra

    def test_empty_body(self) -> None:
        known, extra = split_responses_params({})
        assert known == {}
        assert extra == {}

    def test_tools_is_known_in_responses(self) -> None:
        body = {"tools": []}
        known, _ = split_responses_params(body)
        assert "tools" in known


# ---------------------------------------------------------------------------
# without_stream_request_fields
# ---------------------------------------------------------------------------


class TestWithoutStreamRequestFields:
    def test_removes_stream_fields(self) -> None:
        body = {"model": "gpt-4", "stream": True, "stream_options": {"include_usage": True}}
        result = without_stream_request_fields(body)
        assert "stream" not in result
        assert "stream_options" not in result
        assert result["model"] == "gpt-4"

    def test_no_stream_fields_unchanged(self) -> None:
        body = {"model": "gpt-4", "temperature": 0.5}
        result = without_stream_request_fields(body)
        assert result == {"model": "gpt-4", "temperature": 0.5}

    def test_does_not_modify_original(self) -> None:
        body = {"model": "gpt-4", "stream": True}
        result = without_stream_request_fields(body)
        # Original should be unchanged
        assert "stream" in body
        assert "stream" not in result


# ---------------------------------------------------------------------------
# ensure_chat_stream_usage_options
# ---------------------------------------------------------------------------


class TestEnsureChatStreamUsageOptions:
    def test_adds_stream_options_when_absent(self) -> None:
        body: dict[str, Any] = {"model": "gpt-4"}
        ensure_chat_stream_usage_options(body)
        assert body["stream_options"] == {"include_usage": True}

    def test_existing_stream_options_without_include_usage_gets_it_added(self) -> None:
        body: dict[str, Any] = {"stream_options": {"other": "val"}}
        ensure_chat_stream_usage_options(body)
        assert body["stream_options"]["include_usage"] is True
        assert body["stream_options"]["other"] == "val"

    def test_existing_include_usage_not_overwritten(self) -> None:
        body: dict[str, Any] = {"stream_options": {"include_usage": False}}
        ensure_chat_stream_usage_options(body)
        # Already has include_usage, no change needed
        assert "include_usage" in body["stream_options"]

    def test_non_dict_stream_options_is_replaced(self) -> None:
        body: dict[str, Any] = {"stream_options": None}
        ensure_chat_stream_usage_options(body)
        assert body["stream_options"] == {"include_usage": True}


# ---------------------------------------------------------------------------
# should_fallback_from_stream
# ---------------------------------------------------------------------------


class TestShouldFallbackFromStream:
    def _make_status_error(self, status_code: int, message: str) -> APIStatusError:
        request = httpx.Request("POST", "https://api.example.com/v1/chat/completions")
        response = httpx.Response(status_code, request=request)
        return APIStatusError(message, response=response, body={"error": {"message": message}})

    def test_not_implemented_error_falls_back(self) -> None:
        assert should_fallback_from_stream(NotImplementedError("streaming not supported"))

    def test_generic_exception_does_not_fall_back(self) -> None:
        assert not should_fallback_from_stream(ValueError("something else"))

    def test_stream_related_400_falls_back(self) -> None:
        exc = self._make_status_error(400, "stream is not supported by this model")
        assert should_fallback_from_stream(exc)

    def test_unrelated_400_does_not_fall_back(self) -> None:
        exc = self._make_status_error(400, "invalid request format")
        assert not should_fallback_from_stream(exc)

    def test_unsupported_message_falls_back(self) -> None:
        exc = self._make_status_error(404, "unsupported endpoint")
        assert should_fallback_from_stream(exc)

    def test_500_error_does_not_fall_back(self) -> None:
        exc = self._make_status_error(500, "stream error internal")
        assert not should_fallback_from_stream(exc)

    def test_not_support_message_falls_back(self) -> None:
        exc = self._make_status_error(405, "method not support streaming")
        assert should_fallback_from_stream(exc)


# ---------------------------------------------------------------------------
# stringify_stream_delta
# ---------------------------------------------------------------------------


class TestStringifyStreamDelta:
    def test_none_returns_empty(self) -> None:
        assert stringify_stream_delta(None) == ""

    def test_string_returned_as_is(self) -> None:
        assert stringify_stream_delta("hello") == "hello"

    def test_list_of_strings_joined(self) -> None:
        assert stringify_stream_delta(["a", "b", "c"]) == "abc"

    def test_list_with_none_skipped(self) -> None:
        assert stringify_stream_delta(["a", None, "b"]) == "ab"

    def test_dict_with_text_key(self) -> None:
        assert stringify_stream_delta({"text": "content"}) == "content"

    def test_dict_with_content_key(self) -> None:
        assert stringify_stream_delta({"content": "hello"}) == "hello"

    def test_dict_with_delta_key(self) -> None:
        assert stringify_stream_delta({"delta": "text"}) == "text"

    def test_dict_with_value_key(self) -> None:
        assert stringify_stream_delta({"value": "val"}) == "val"

    def test_dict_without_known_keys_empty(self) -> None:
        assert stringify_stream_delta({"unknown": "x"}) == ""

    def test_non_string_becomes_str(self) -> None:
        assert stringify_stream_delta(42) == "42"

    def test_empty_string_returned_as_is(self) -> None:
        assert stringify_stream_delta("") == ""


# ---------------------------------------------------------------------------
# extract_stream_response_item
# ---------------------------------------------------------------------------


class TestExtractStreamResponseItem:
    def test_item_key_returned(self) -> None:
        event = {"item": {"type": "message", "content": "x"}}
        result = extract_stream_response_item(event)
        assert result == {"type": "message", "content": "x"}

    def test_output_item_key_returned(self) -> None:
        event = {"output_item": {"type": "function_call"}}
        result = extract_stream_response_item(event)
        assert result == {"type": "function_call"}

    def test_data_key_returned(self) -> None:
        event = {"data": {"type": "reasoning"}}
        result = extract_stream_response_item(event)
        assert result == {"type": "reasoning"}

    def test_response_with_output_list_returns_none(self) -> None:
        event = {"response": {"output": [{"type": "message"}]}}
        result = extract_stream_response_item(event)
        assert result is None

    def test_response_dict_without_output_list_returned(self) -> None:
        event = {"response": {"id": "resp_123"}}
        result = extract_stream_response_item(event)
        assert result == {"id": "resp_123"}

    def test_no_known_keys_returns_none(self) -> None:
        event = {"unknown": "x"}
        result = extract_stream_response_item(event)
        assert result is None


# ---------------------------------------------------------------------------
# extract_stream_usage
# ---------------------------------------------------------------------------


class TestExtractStreamUsage:
    def test_chat_completions_usage(self) -> None:
        event = {"usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}}
        result = extract_stream_usage(event, api_mode="chat_completions")
        assert result == {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}

    def test_responses_usage(self) -> None:
        event = {"usage": {"input_tokens": 8, "output_tokens": 4, "total_tokens": 12}}
        result = extract_stream_usage(event, api_mode="responses")
        assert result == {"input_tokens": 8, "output_tokens": 4, "total_tokens": 12}

    def test_no_usage_returns_none(self) -> None:
        event = {"type": "text.delta"}
        result = extract_stream_usage(event, api_mode="chat_completions")
        assert result is None

    def test_usage_from_nested_response(self) -> None:
        event = {
            "response": {
                "usage": {"input_tokens": 3, "output_tokens": 2, "total_tokens": 5}
            }
        }
        result = extract_stream_usage(event, api_mode="responses")
        assert result == {"input_tokens": 3, "output_tokens": 2, "total_tokens": 5}

    def test_missing_usage_fields_default_to_zero(self) -> None:
        event = {"usage": {}}
        result = extract_stream_usage(event, api_mode="chat_completions")
        assert result is not None
        assert result["prompt_tokens"] == 0
        assert result["completion_tokens"] == 0
        assert result["total_tokens"] == 0


# ---------------------------------------------------------------------------
# ensure_tool_call_slot
# ---------------------------------------------------------------------------


class TestEnsureToolCallSlot:
    def test_creates_slot_when_empty(self) -> None:
        tool_calls: list[dict[str, Any]] = []
        slot = ensure_tool_call_slot(tool_calls, 0)
        assert len(tool_calls) == 1
        assert slot is tool_calls[0]
        assert slot["id"] == ""
        assert slot["type"] == "function"

    def test_creates_multiple_slots(self) -> None:
        tool_calls: list[dict[str, Any]] = []
        slot = ensure_tool_call_slot(tool_calls, 2)
        assert len(tool_calls) == 3
        assert slot is tool_calls[2]

    def test_existing_slot_returned(self) -> None:
        existing = {"id": "call_1", "type": "function", "function": {"name": "foo", "arguments": ""}}
        tool_calls = [existing]
        slot = ensure_tool_call_slot(tool_calls, 0)
        assert slot is existing
        assert len(tool_calls) == 1


# ---------------------------------------------------------------------------
# merge_tool_call_delta
# ---------------------------------------------------------------------------


class TestMergeToolCallDelta:
    def test_creates_slot_and_sets_id(self) -> None:
        tool_calls: list[dict[str, Any]] = []
        delta = {"index": 0, "id": "call_abc", "type": "function", "function": {"name": "my_tool", "arguments": ""}}
        merge_tool_call_delta(tool_calls, delta)
        assert tool_calls[0]["id"] == "call_abc"
        assert tool_calls[0]["function"]["name"] == "my_tool"

    def test_appends_arguments_delta(self) -> None:
        tool_calls: list[dict[str, Any]] = []
        merge_tool_call_delta(tool_calls, {"index": 0, "id": "c1", "function": {"name": "foo", "arguments": '{"k"'}})
        merge_tool_call_delta(tool_calls, {"index": 0, "function": {"arguments": ': "v"}'}})
        assert tool_calls[0]["function"]["arguments"] == '{"k": "v"}'

    def test_non_dict_function_delta_ignored(self) -> None:
        tool_calls: list[dict[str, Any]] = []
        delta = {"index": 0, "id": "c1", "function": None}
        merge_tool_call_delta(tool_calls, delta)
        assert len(tool_calls) == 1
        # function delta was None, so function should remain default
        assert "function" in tool_calls[0]

    def test_index_none_appends_to_end(self) -> None:
        tool_calls: list[dict[str, Any]] = [
            {"id": "c1", "type": "function", "function": {"name": "a", "arguments": ""}}
        ]
        delta = {"index": None, "id": "c2", "function": {"name": "b", "arguments": ""}}
        merge_tool_call_delta(tool_calls, delta)
        assert len(tool_calls) == 2
        assert tool_calls[1]["id"] == "c2"


# ---------------------------------------------------------------------------
# aggregate_chat_completions_stream
# ---------------------------------------------------------------------------


class TestAggregateChatCompletionsStream:
    def _text_chunk(self, content: str, role: str = "assistant") -> dict[str, Any]:
        return {
            "choices": [{"delta": {"role": role, "content": content}, "finish_reason": None}]
        }

    def _final_chunk(self, finish_reason: str = "stop") -> dict[str, Any]:
        return {"choices": [{"delta": {}, "finish_reason": finish_reason}]}

    def test_empty_chunks_returns_empty_message(self) -> None:
        result = aggregate_chat_completions_stream([], reasoning_replay=False)
        assert result["choices"][0]["message"]["content"] == ""
        assert result["choices"][0]["finish_reason"] == "stop"

    def test_text_chunks_concatenated(self) -> None:
        chunks = [
            self._text_chunk("Hello"),
            self._text_chunk(", "),
            self._text_chunk("world"),
            self._final_chunk(),
        ]
        result = aggregate_chat_completions_stream(chunks, reasoning_replay=False)
        assert result["choices"][0]["message"]["content"] == "Hello, world"

    def test_finish_reason_captured(self) -> None:
        chunks = [self._final_chunk("tool_calls")]
        result = aggregate_chat_completions_stream(chunks, reasoning_replay=False)
        assert result["choices"][0]["finish_reason"] == "tool_calls"

    def test_usage_extracted(self) -> None:
        chunks = [
            self._text_chunk("hi"),
            {"usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8}},
        ]
        result = aggregate_chat_completions_stream(chunks, reasoning_replay=False)
        assert result["usage"]["total_tokens"] == 8

    def test_tool_calls_aggregated(self) -> None:
        chunks = [
            {
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {"index": 0, "id": "call_1", "type": "function", "function": {"name": "send_message", "arguments": '{"msg"'}}
                            ]
                        },
                        "finish_reason": None,
                    }
                ]
            },
            {
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {"index": 0, "function": {"arguments": ': "hello"}'}}
                            ]
                        },
                        "finish_reason": "tool_calls",
                    }
                ]
            },
        ]
        result = aggregate_chat_completions_stream(chunks, reasoning_replay=False)
        msg = result["choices"][0]["message"]
        assert "tool_calls" in msg
        assert msg["tool_calls"][0]["function"]["arguments"] == '{"msg": "hello"}'

    def test_reasoning_content_collected_when_replay_enabled(self) -> None:
        chunks = [
            {
                "choices": [
                    {"delta": {"reasoning_content": "thinking step 1"}, "finish_reason": None}
                ]
            },
            {
                "choices": [
                    {"delta": {"reasoning_content": " step 2"}, "finish_reason": "stop"}
                ]
            },
        ]
        result = aggregate_chat_completions_stream(chunks, reasoning_replay=True)
        msg = result["choices"][0]["message"]
        assert "reasoning_content" in msg
        assert "thinking step 1" in msg["reasoning_content"]

    def test_reasoning_content_not_collected_when_replay_disabled(self) -> None:
        chunks = [
            {
                "choices": [
                    {"delta": {"reasoning_content": "thoughts"}, "finish_reason": "stop"}
                ]
            }
        ]
        result = aggregate_chat_completions_stream(chunks, reasoning_replay=False)
        msg = result["choices"][0]["message"]
        assert "reasoning_content" not in msg


# ---------------------------------------------------------------------------
# aggregate_responses_stream
# ---------------------------------------------------------------------------


class TestAggregateResponsesStream:
    def test_empty_events_returns_empty_output(self) -> None:
        result = aggregate_responses_stream([])
        assert result.get("output") == []
        assert result.get("output_text") == ""

    def test_completed_event_with_final_response(self) -> None:
        final_resp = {
            "id": "resp_123",
            "output": [{"type": "message", "content": "hi"}],
        }
        events = [{"type": "response.completed", "response": final_resp}]
        result = aggregate_responses_stream(events)
        assert result["id"] == "resp_123"

    def test_output_text_delta_accumulated(self) -> None:
        events = [
            {"type": "response.output_text.delta", "delta": "Hello"},
            {"type": "response.output_text.delta", "delta": " World"},
        ]
        result = aggregate_responses_stream(events)
        assert result.get("output_text") == "Hello World"

    def test_usage_extracted_from_completed(self) -> None:
        final_resp = {
            "id": "resp_456",
            "output": [],
            "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        }
        events = [{"type": "response.completed", "response": final_resp}]
        result = aggregate_responses_stream(events)
        assert result["usage"]["total_tokens"] == 15

    def test_usage_injected_into_final_response_if_missing(self) -> None:
        usage_event = {
            "usage": {"input_tokens": 3, "output_tokens": 2, "total_tokens": 5}
        }
        final_resp = {"id": "resp_789", "output": []}
        events = [
            usage_event,
            {"type": "response.completed", "response": final_resp},
        ]
        result = aggregate_responses_stream(events)
        assert result["usage"]["total_tokens"] == 5

    def test_message_output_items_collected_without_completed(self) -> None:
        events = [
            {"item": {"type": "message", "content": "hello"}},
            {"item": {"type": "function_call", "name": "end"}},
        ]
        result = aggregate_responses_stream(events)
        assert len(result.get("output", [])) == 2