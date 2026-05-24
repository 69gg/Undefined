"""Tests for Undefined.ai.llm.sanitize — tool-name encoding and message sanitization."""

from __future__ import annotations

from typing import Any, cast

from Undefined.ai.llm.sanitize import (
    CHAT_COMPLETION_INTERNAL_MESSAGE_KEYS,
    _clean_control_chars,
    _encode_tool_name_for_api,
    _normalize_tool_description,
    prepare_chat_completion_messages,
    relocate_system_to_first_user,
    sanitize_chat_completion_messages,
    sanitize_openai_messages_tool_arguments,
    sanitize_openai_tool_names_in_request,
    sanitize_openai_tools,
)


# ---------------------------------------------------------------------------
# _clean_control_chars
# ---------------------------------------------------------------------------


class TestCleanControlChars:
    def test_removes_ascii_control_characters(self) -> None:
        text = "hello\x00world\x1f!"
        assert _clean_control_chars(text) == "hello world !"

    def test_removes_del_character(self) -> None:
        text = "a\x7fb"
        assert _clean_control_chars(text) == "a b"

    def test_keeps_normal_text(self) -> None:
        text = "hello world 123"
        assert _clean_control_chars(text) == "hello world 123"

    def test_keeps_newline_and_tab(self) -> None:
        # \n is ord 10, \t is ord 9 — both < 32, so they ARE replaced
        text = "a\nb\tc"
        assert _clean_control_chars(text) == "a b c"

    def test_empty_string(self) -> None:
        assert _clean_control_chars("") == ""

    def test_unicode_above_127_kept(self) -> None:
        text = "你好世界"
        assert _clean_control_chars(text) == "你好世界"


# ---------------------------------------------------------------------------
# _encode_tool_name_for_api
# ---------------------------------------------------------------------------


class TestEncodeToolNameForApi:
    def test_simple_name_unchanged(self) -> None:
        assert _encode_tool_name_for_api("send_message") == "send_message"

    def test_dot_replaced_by_delimiter(self) -> None:
        result = _encode_tool_name_for_api("group.send")
        assert "." not in result
        assert "send" in result

    def test_empty_name_returns_tool(self) -> None:
        assert _encode_tool_name_for_api("") == "tool"

    def test_whitespace_only_returns_tool(self) -> None:
        assert _encode_tool_name_for_api("   ") == "tool"

    def test_illegal_chars_replaced(self) -> None:
        result = _encode_tool_name_for_api("my tool@name")
        import re

        assert re.match(r"^[a-zA-Z0-9_-]+$", result)

    def test_long_name_truncated_to_64(self) -> None:
        long_name = "a" * 100
        result = _encode_tool_name_for_api(long_name)
        assert len(result) <= 64

    def test_exactly_64_chars_name_unchanged(self) -> None:
        name = "a" * 64
        result = _encode_tool_name_for_api(name)
        assert len(result) == 64
        assert result == name

    def test_name_with_hyphen_and_underscore_kept(self) -> None:
        name = "my-tool_name"
        assert _encode_tool_name_for_api(name) == "my-tool_name"


# ---------------------------------------------------------------------------
# _normalize_tool_description
# ---------------------------------------------------------------------------


class TestNormalizeToolDescription:
    def test_none_description_becomes_function_name(self) -> None:
        result = _normalize_tool_description(None, "my_tool", 1024, False)
        assert result == "Tool function my_tool"

    def test_string_description_whitespace_normalized(self) -> None:
        desc = "  hello   world  \n  test  "
        result = _normalize_tool_description(desc, "t", 1024, False)
        assert result == "hello world test"

    def test_non_string_description_converted(self) -> None:
        result = _normalize_tool_description(123, "t", 1024, False)
        assert result == "123"

    def test_truncation_when_enabled(self) -> None:
        desc = "a" * 200
        result = _normalize_tool_description(desc, "t", 100, True)
        assert len(result) <= 100

    def test_no_truncation_when_disabled(self) -> None:
        desc = "a" * 200
        result = _normalize_tool_description(desc, "t", 100, False)
        assert len(result) == 200

    def test_empty_string_becomes_function_name(self) -> None:
        result = _normalize_tool_description("   ", "my_tool", 1024, False)
        assert result == "Tool function my_tool"

    def test_control_chars_removed(self) -> None:
        desc = "hello\x00world"
        result = _normalize_tool_description(desc, "t", 1024, False)
        assert "\x00" not in result


# ---------------------------------------------------------------------------
# sanitize_openai_tools
# ---------------------------------------------------------------------------


class TestSanitizeOpenaiTools:
    def _make_tool(self, name: str, description: Any) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {"name": name, "description": description},
        }

    def test_empty_tools_returned_unchanged(self) -> None:
        result, changed, changes = sanitize_openai_tools([])
        assert result == []
        assert changed == 0
        assert changes == []

    def test_clean_description_not_changed(self) -> None:
        tools = [self._make_tool("foo", "A normal description.")]
        result, changed, _ = sanitize_openai_tools(tools)
        assert changed == 0
        assert result[0]["function"]["description"] == "A normal description."

    def test_none_description_replaced(self) -> None:
        tools = [self._make_tool("foo", None)]
        result, changed, changes = sanitize_openai_tools(tools)
        assert changed == 1
        assert result[0]["function"]["description"] == "Tool function foo"
        assert len(changes) == 1
        assert changes[0]["name"] == "foo"
        assert "empty" in changes[0]["reasons"]

    def test_description_with_control_chars_cleaned(self) -> None:
        tools = [self._make_tool("bar", "hello\x00world")]
        result, changed, changes = sanitize_openai_tools(tools)
        assert changed == 1
        assert "\x00" not in result[0]["function"]["description"]

    def test_description_with_newlines_normalized(self) -> None:
        tools = [self._make_tool("baz", "line1\nline2")]
        result, changed, changes = sanitize_openai_tools(tools)
        assert changed == 1
        assert "\n" not in result[0]["function"]["description"]
        assert "whitespace" in changes[0]["reasons"]

    def test_non_dict_tools_passed_through(self) -> None:
        tools = cast(list[dict[str, Any]], ["not_a_dict"])
        result, changed, _ = sanitize_openai_tools(tools)
        assert result == cast(list[dict[str, Any]], ["not_a_dict"])
        assert changed == 0

    def test_tool_without_function_key_passed_through(self) -> None:
        tools = [{"type": "other"}]
        result, changed, _ = sanitize_openai_tools(tools)
        assert result == [{"type": "other"}]
        assert changed == 0

    def test_multiple_tools_mixed(self) -> None:
        tools = [
            self._make_tool("clean", "Clean description"),
            self._make_tool("dirty", "has\nnewline"),
        ]
        result, changed, _ = sanitize_openai_tools(tools)
        assert changed == 1
        assert result[0]["function"]["description"] == "Clean description"
        assert "\n" not in result[1]["function"]["description"]

    def test_non_string_description_marked_non_string(self) -> None:
        tools = [self._make_tool("t", None)]
        result, changed, changes = sanitize_openai_tools(tools)
        assert changed == 1
        assert "non_string" in changes[0]["reasons"]
        assert result[0]["function"]["description"] == "Tool function t"


# ---------------------------------------------------------------------------
# sanitize_openai_tool_names_in_request
# ---------------------------------------------------------------------------


class TestSanitizeOpenaiToolNamesInRequest:
    def _make_request(self, tools: list[dict[str, Any]]) -> dict[str, Any]:
        return {"tools": tools, "messages": []}

    def test_empty_tools_returns_empty_dicts(self) -> None:
        body: dict[str, Any] = {"tools": [], "messages": []}
        api_to_internal, internal_to_api = sanitize_openai_tool_names_in_request(body)
        assert api_to_internal == {}
        assert internal_to_api == {}

    def test_simple_name_not_rewritten(self) -> None:
        body: dict[str, Any] = {
            "tools": [{"type": "function", "function": {"name": "send_message"}}],
            "messages": [],
        }
        api_to_internal, internal_to_api = sanitize_openai_tool_names_in_request(body)
        assert api_to_internal == {"send_message": "send_message"}
        assert internal_to_api == {"send_message": "send_message"}
        assert body["tools"][0]["function"]["name"] == "send_message"

    def test_dotted_name_rewritten(self) -> None:
        body: dict[str, Any] = {
            "tools": [{"type": "function", "function": {"name": "group.send"}}],
            "messages": [],
        }
        api_to_internal, internal_to_api = sanitize_openai_tool_names_in_request(body)
        api_name = body["tools"][0]["function"]["name"]
        assert "." not in api_name
        assert api_to_internal[api_name] == "group.send"
        assert internal_to_api["group.send"] == api_name

    def test_messages_tool_call_names_rewritten(self) -> None:
        body: dict[str, Any] = {
            "tools": [{"type": "function", "function": {"name": "group.send"}}],
            "messages": [
                {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "id": "c1",
                            "function": {"name": "group.send", "arguments": "{}"},
                        }
                    ],
                }
            ],
        }
        api_to_internal, _ = sanitize_openai_tool_names_in_request(body)
        tool_call = body["messages"][0]["tool_calls"][0]
        api_name = list(api_to_internal.keys())[0]
        assert tool_call["function"]["name"] == api_name

    def test_message_name_field_rewritten(self) -> None:
        body: dict[str, Any] = {
            "tools": [{"type": "function", "function": {"name": "group.send"}}],
            "messages": [{"role": "tool", "name": "group.send", "content": "result"}],
        }
        sanitize_openai_tool_names_in_request(body)
        # The message name should be rewritten to the api name
        msg_name = body["messages"][0]["name"]
        assert "." not in msg_name

    def test_no_tools_key_returns_empty(self) -> None:
        body: dict[str, Any] = {"messages": []}
        api_to_internal, internal_to_api = sanitize_openai_tool_names_in_request(body)
        assert api_to_internal == {}
        assert internal_to_api == {}


# ---------------------------------------------------------------------------
# sanitize_openai_messages_tool_arguments
# ---------------------------------------------------------------------------


class TestSanitizeOpenaiMessagesToolArguments:
    def test_empty_messages(self) -> None:
        result, changed = sanitize_openai_messages_tool_arguments([])
        assert result == []
        assert changed == 0

    def test_messages_without_tool_calls_unchanged(self) -> None:
        messages = [{"role": "user", "content": "hello"}]
        result, changed = sanitize_openai_messages_tool_arguments(messages)
        assert result == messages
        assert changed == 0

    def test_valid_json_arguments_unchanged(self) -> None:
        arguments = '{"key":"val"}'
        messages = [
            {
                "role": "assistant",
                "tool_calls": [
                    {"id": "c1", "function": {"name": "tool", "arguments": arguments}}
                ],
            }
        ]
        result, changed = sanitize_openai_messages_tool_arguments(messages)
        assert changed == 0
        assert result[0]["tool_calls"][0]["function"]["arguments"] == arguments

    def test_none_arguments_normalized(self) -> None:
        messages = [
            {
                "role": "assistant",
                "tool_calls": [
                    {"id": "c1", "function": {"name": "tool", "arguments": None}}
                ],
            }
        ]
        result, changed = sanitize_openai_messages_tool_arguments(messages)
        assert changed == 1
        # Result should be a valid JSON string (e.g. "{}")
        args = result[0]["tool_calls"][0]["function"]["arguments"]
        import json

        json.loads(args)  # should not raise

    def test_non_dict_message_passed_through(self) -> None:
        messages = cast(list[dict[str, Any]], ["not_a_dict"])
        result, changed = sanitize_openai_messages_tool_arguments(messages)
        assert result == cast(list[dict[str, Any]], ["not_a_dict"])
        assert changed == 0


# ---------------------------------------------------------------------------
# sanitize_chat_completion_messages
# ---------------------------------------------------------------------------


class TestSanitizeChatCompletionMessages:
    def test_empty_messages(self) -> None:
        result, changed, stripped = sanitize_chat_completion_messages([])
        assert result == []
        assert changed == 0
        assert stripped == {}

    def test_reasoning_content_stripped_by_default(self) -> None:
        messages = [
            {"role": "assistant", "content": "hi", "reasoning_content": "thoughts"}
        ]
        result, changed, stripped = sanitize_chat_completion_messages(messages)
        assert changed == 1
        assert "reasoning_content" not in result[0]
        assert stripped.get("reasoning_content", 0) == 1

    def test_reasoning_content_preserved_when_flag_set(self) -> None:
        messages = [
            {"role": "assistant", "content": "hi", "reasoning_content": "thoughts"}
        ]
        result, changed, stripped = sanitize_chat_completion_messages(
            messages, preserve_reasoning_content=True
        )
        assert changed == 0
        assert result[0].get("reasoning_content") == "thoughts"

    def test_phase_field_stripped(self) -> None:
        messages = [{"role": "assistant", "content": "hi", "phase": "thinking"}]
        result, changed, stripped = sanitize_chat_completion_messages(messages)
        assert changed == 1
        assert "phase" not in result[0]

    def test_responses_output_items_stripped(self) -> None:
        messages = [
            {"role": "assistant", "content": "ok", "_responses_output_items": []}
        ]
        result, changed, stripped = sanitize_chat_completion_messages(messages)
        assert changed == 1
        assert "_responses_output_items" not in result[0]

    def test_thinking_keys_stripped(self) -> None:
        for key in ("thinking", "reasoning", "chain_of_thought", "cot", "thoughts"):
            messages = [{"role": "assistant", "content": "x", key: "value"}]
            result, changed, stripped = sanitize_chat_completion_messages(messages)
            assert changed == 1, f"Expected key {key!r} to be stripped"
            assert key not in result[0]

    def test_normal_messages_not_modified(self) -> None:
        messages = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "world"},
        ]
        result, changed, stripped = sanitize_chat_completion_messages(messages)
        assert changed == 0
        assert result == messages

    def test_non_dict_message_passed_through(self) -> None:
        messages = cast(list[dict[str, Any]], ["not_a_dict"])
        result, changed, _ = sanitize_chat_completion_messages(messages)
        assert result == cast(list[dict[str, Any]], ["not_a_dict"])
        assert changed == 0

    def test_all_internal_keys_listed_in_constant(self) -> None:
        # Verify the public constant is correct
        assert "reasoning_content" in CHAT_COMPLETION_INTERNAL_MESSAGE_KEYS
        assert "_responses_output_items" in CHAT_COMPLETION_INTERNAL_MESSAGE_KEYS
        assert "phase" in CHAT_COMPLETION_INTERNAL_MESSAGE_KEYS


# ---------------------------------------------------------------------------
# relocate_system_to_first_user
# ---------------------------------------------------------------------------


class TestRelocateSystemToFirstUser:
    def test_empty_messages(self) -> None:
        assert relocate_system_to_first_user([]) == []

    def test_no_system_message_unchanged(self) -> None:
        messages = [{"role": "user", "content": "hello"}]
        result = relocate_system_to_first_user(messages)
        assert result == messages

    def test_system_merged_into_first_user(self) -> None:
        messages = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hi"},
        ]
        result = relocate_system_to_first_user(messages)
        assert len(result) == 1
        assert result[0]["role"] == "user"
        assert "You are helpful." in result[0]["content"]
        assert "Hi" in result[0]["content"]

    def test_system_with_no_user_becomes_user_message(self) -> None:
        messages = [{"role": "system", "content": "Instructions"}]
        result = relocate_system_to_first_user(messages)
        assert len(result) == 1
        assert result[0]["role"] == "user"
        assert result[0]["content"] == "Instructions"

    def test_developer_role_treated_as_system(self) -> None:
        messages = [
            {"role": "developer", "content": "Developer instructions"},
            {"role": "user", "content": "Hello"},
        ]
        result = relocate_system_to_first_user(messages)
        assert len(result) == 1
        assert result[0]["role"] == "user"
        assert "Developer instructions" in result[0]["content"]

    def test_multiple_system_messages_merged(self) -> None:
        messages = [
            {"role": "system", "content": "Part 1"},
            {"role": "system", "content": "Part 2"},
            {"role": "user", "content": "User msg"},
        ]
        result = relocate_system_to_first_user(messages)
        assert len(result) == 1
        assert "Part 1" in result[0]["content"]
        assert "Part 2" in result[0]["content"]

    def test_system_prepended_to_existing_user_content(self) -> None:
        messages = [
            {"role": "system", "content": "SYS"},
            {"role": "user", "content": "USER"},
        ]
        result = relocate_system_to_first_user(messages)
        content = result[0]["content"]
        # System should come before user content
        assert content.index("SYS") < content.index("USER")

    def test_non_dict_messages_passed_through(self) -> None:
        messages = cast(
            list[dict[str, Any]],
            ["not_dict", {"role": "user", "content": "hi"}],
        )
        result = relocate_system_to_first_user(messages)
        # non-dict item treated as "remaining" (no role to strip)
        assert "not_dict" in cast(list[Any], result)


# ---------------------------------------------------------------------------
# prepare_chat_completion_messages
# ---------------------------------------------------------------------------


class TestPrepareChatCompletionMessages:
    def _make_config(
        self,
        *,
        reasoning_content_replay: bool = False,
        system_prompt_as_user: bool = False,
    ) -> Any:
        from types import SimpleNamespace

        return SimpleNamespace(
            reasoning_content_replay=reasoning_content_replay,
            system_prompt_as_user=system_prompt_as_user,
        )

    def test_strips_internal_fields(self) -> None:
        cfg = self._make_config()
        messages = [{"role": "assistant", "content": "hi", "reasoning_content": "x"}]
        result = prepare_chat_completion_messages(cfg, messages)
        assert "reasoning_content" not in result[0]

    def test_preserves_reasoning_content_when_replay_enabled(self) -> None:
        cfg = self._make_config(reasoning_content_replay=True)
        messages = [{"role": "assistant", "content": "hi", "reasoning_content": "x"}]
        result = prepare_chat_completion_messages(cfg, messages)
        assert result[0].get("reasoning_content") == "x"

    def test_relocates_system_when_flag_enabled(self) -> None:
        cfg = self._make_config(system_prompt_as_user=True)
        messages = [
            {"role": "system", "content": "Instructions"},
            {"role": "user", "content": "Hello"},
        ]
        result = prepare_chat_completion_messages(cfg, messages)
        assert all(msg["role"] != "system" for msg in result)

    def test_no_relocation_when_flag_disabled(self) -> None:
        cfg = self._make_config(system_prompt_as_user=False)
        messages = [
            {"role": "system", "content": "Instructions"},
            {"role": "user", "content": "Hello"},
        ]
        result = prepare_chat_completion_messages(cfg, messages)
        assert any(msg["role"] == "system" for msg in result)
