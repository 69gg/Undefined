"""Tests for ai/client/setup.py — utility functions and ClientSetupMixin methods."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest

from Undefined.ai.client.setup import (
    MISSING_TOOL_CALL_RETRY_HINT,
    ClientSetupMixin,
    _attachment_cache_max_age_seconds,
    _attachment_cache_max_bytes,
    _attachment_remote_download_max_bytes,
    _build_invalid_tool_call_response,
    _INVALID_TOOL_CALL_CONTENT,
)
from Undefined.context import RequestContext


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_runtime_config(**kwargs: Any) -> Any:
    """Build a minimal SimpleNamespace that satisfies the runtime_config interface."""
    from Undefined.config.models import NagaConfig

    defaults: dict[str, Any] = {
        "attachment_remote_download_max_size_mb": 50,
        "attachment_cache_max_total_size_mb": 200,
        "attachment_cache_max_age_days": 7,
        "attachment_cache_max_records": 1000,
        "attachment_url_reference_max_records": 500,
        "attachment_url_max_length": 4096,
        "summary_model_configured": False,
        "summary_model": None,
        "nagaagent_mode_enabled": False,
        "naga": NagaConfig(mode="off"),
        "prefetch_tools": [],
        "prefetch_tools_hide": False,
        "tools_dot_delimiter": "-_-",
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _make_client_setup_mixin(**kwargs: Any) -> Any:
    """Create a ClientSetupMixin instance bypassing __init__."""
    obj = cast(Any, ClientSetupMixin.__new__(ClientSetupMixin))
    obj.runtime_config = _make_runtime_config()
    # Minimal attributes referenced by methods
    obj._pending_llm_calls = {}
    obj._queue_manager = None
    obj._intro_config = None
    obj._intro_refresh_task = None
    obj._cognitive_service = None
    obj._knowledge_manager = None
    for k, v in kwargs.items():
        setattr(obj, k, v)
    return obj


# ---------------------------------------------------------------------------
# _attachment_remote_download_max_bytes
# ---------------------------------------------------------------------------


class TestAttachmentRemoteDownloadMaxBytes:
    def test_positive_value_converted(self) -> None:
        cfg = _make_runtime_config(attachment_remote_download_max_size_mb=10)
        assert _attachment_remote_download_max_bytes(cfg) == 10 * 1024 * 1024

    def test_zero_value(self) -> None:
        cfg = _make_runtime_config(attachment_remote_download_max_size_mb=0)
        assert _attachment_remote_download_max_bytes(cfg) == 0

    def test_negative_clamped_to_zero(self) -> None:
        cfg = _make_runtime_config(attachment_remote_download_max_size_mb=-5)
        assert _attachment_remote_download_max_bytes(cfg) == 0

    def test_large_value(self) -> None:
        cfg = _make_runtime_config(attachment_remote_download_max_size_mb=100)
        assert _attachment_remote_download_max_bytes(cfg) == 100 * 1024 * 1024


# ---------------------------------------------------------------------------
# _attachment_cache_max_bytes
# ---------------------------------------------------------------------------


class TestAttachmentCacheMaxBytes:
    def test_positive_value_converted(self) -> None:
        cfg = _make_runtime_config(attachment_cache_max_total_size_mb=200)
        assert _attachment_cache_max_bytes(cfg) == 200 * 1024 * 1024

    def test_zero_value(self) -> None:
        cfg = _make_runtime_config(attachment_cache_max_total_size_mb=0)
        assert _attachment_cache_max_bytes(cfg) == 0

    def test_negative_clamped_to_zero(self) -> None:
        cfg = _make_runtime_config(attachment_cache_max_total_size_mb=-1)
        assert _attachment_cache_max_bytes(cfg) == 0


# ---------------------------------------------------------------------------
# _attachment_cache_max_age_seconds
# ---------------------------------------------------------------------------


class TestAttachmentCacheMaxAgeSeconds:
    def test_converts_days_to_seconds(self) -> None:
        cfg = _make_runtime_config(attachment_cache_max_age_days=7)
        assert _attachment_cache_max_age_seconds(cfg) == 7 * 24 * 60 * 60

    def test_zero_days(self) -> None:
        cfg = _make_runtime_config(attachment_cache_max_age_days=0)
        assert _attachment_cache_max_age_seconds(cfg) == 0

    def test_negative_days_clamped_to_zero(self) -> None:
        cfg = _make_runtime_config(attachment_cache_max_age_days=-3)
        assert _attachment_cache_max_age_seconds(cfg) == 0

    def test_one_day_is_86400_seconds(self) -> None:
        cfg = _make_runtime_config(attachment_cache_max_age_days=1)
        assert _attachment_cache_max_age_seconds(cfg) == 86400


# ---------------------------------------------------------------------------
# MISSING_TOOL_CALL_RETRY_HINT
# ---------------------------------------------------------------------------


class TestMissingToolCallRetryHint:
    def test_is_non_empty_string(self) -> None:
        assert isinstance(MISSING_TOOL_CALL_RETRY_HINT, str)
        assert len(MISSING_TOOL_CALL_RETRY_HINT) > 0

    def test_contains_system_context(self) -> None:
        assert "系统提示" in MISSING_TOOL_CALL_RETRY_HINT

    def test_mentions_tool_requirement(self) -> None:
        assert "工具" in MISSING_TOOL_CALL_RETRY_HINT


# ---------------------------------------------------------------------------
# _build_invalid_tool_call_response (additional edge cases)
# ---------------------------------------------------------------------------


class TestBuildInvalidToolCallResponseEdgeCases:
    def test_tool_name_with_spaces_stripped(self) -> None:
        response = _build_invalid_tool_call_response(
            {"id": "c1", "function": {"name": "  my_tool  ", "arguments": "{}"}}
        )
        # The .strip() call in setup.py strips whitespace
        assert response["name"] == "my_tool"

    def test_none_id_becomes_empty_string(self) -> None:
        response = _build_invalid_tool_call_response(
            {"id": None, "function": {"name": "foo"}}
        )
        assert response["tool_call_id"] == ""

    def test_function_key_not_dict_yields_empty_name(self) -> None:
        response = _build_invalid_tool_call_response(
            {"id": "c1", "function": "not_a_dict"}
        )
        assert response["name"] == ""

    def test_content_is_invalid_tool_call_constant(self) -> None:
        response = _build_invalid_tool_call_response({})
        assert response["content"] == _INVALID_TOOL_CALL_CONTENT

    def test_list_input_treated_as_non_dict(self) -> None:
        response = _build_invalid_tool_call_response(cast(Any, [1, 2, 3]))
        assert response["role"] == "tool"
        assert response["tool_call_id"] == ""


# ---------------------------------------------------------------------------
# ClientSetupMixin._is_missing_tool_result
# ---------------------------------------------------------------------------


class TestIsMissingToolResult:
    def setup_method(self) -> None:
        self.client = _make_client_setup_mixin()

    def test_missing_project_result(self) -> None:
        assert self.client._is_missing_tool_result("未找到项目 foo")

    def test_missing_mcp_tool_result(self) -> None:
        assert self.client._is_missing_tool_result("未找到 MCP 工具 bar")

    def test_normal_result_false(self) -> None:
        assert not self.client._is_missing_tool_result("success")

    def test_non_string_result_false(self) -> None:
        assert not self.client._is_missing_tool_result({"result": "ok"})

    def test_empty_string_false(self) -> None:
        assert not self.client._is_missing_tool_result("")


class TestHidePrefetchToolSchemas:
    def setup_method(self) -> None:
        self.client = _make_client_setup_mixin()

    @staticmethod
    def _tool(name: str) -> dict[str, Any]:
        return {"type": "function", "function": {"name": name}}

    def test_hides_successfully_prefetched_tools(self) -> None:
        self.client.runtime_config = _make_runtime_config(
            prefetch_tools=["get_current_time"],
            prefetch_tools_hide=True,
        )
        tools = [self._tool("get_current_time"), self._tool("end")]

        assert self.client._hide_prefetch_tool_schemas(tools, {"get_current_time"}) == [
            self._tool("end")
        ]

    def test_keeps_prefetch_tools_without_a_successful_result(self) -> None:
        self.client.runtime_config = _make_runtime_config(
            prefetch_tools=["get_current_time"],
            prefetch_tools_hide=True,
        )
        tools = [self._tool("get_current_time"), self._tool("end")]

        assert self.client._hide_prefetch_tool_schemas(tools, set()) == tools

    def test_keeps_tools_when_prefetch_hiding_is_disabled(self) -> None:
        self.client.runtime_config = _make_runtime_config(
            prefetch_tools=["get_current_time"],
            prefetch_tools_hide=False,
        )
        tools = [self._tool("get_current_time"), self._tool("end")]

        assert (
            self.client._hide_prefetch_tool_schemas(tools, {"get_current_time"})
            == tools
        )

    def test_virtual_tool_search_cannot_be_hidden_by_prefetch_config(self) -> None:
        self.client.runtime_config = _make_runtime_config(
            prefetch_tools=["tool_search"],
            prefetch_tools_hide=True,
        )
        tools = [self._tool("tool_search"), self._tool("end")]

        assert self.client._hide_prefetch_tool_schemas(tools, {"tool_search"}) == tools

    @pytest.mark.asyncio
    async def test_prefetch_result_stays_in_messages_and_is_not_executed_twice(
        self,
    ) -> None:
        self.client.runtime_config = _make_runtime_config(
            prefetch_tools=["get_current_time"],
            prefetch_tools_hide=True,
        )
        execute_tool = AsyncMock(return_value="2026-07-10 12:00:00")
        self.client.tool_manager = SimpleNamespace(execute_tool=execute_tool)
        tools = [self._tool("get_current_time"), self._tool("end")]

        first_messages, first_tools = await self.client._maybe_prefetch_tools(
            [{"role": "system", "content": "system"}], tools, "chat"
        )
        second_messages, second_tools = await self.client._maybe_prefetch_tools(
            first_messages, tools, "chat"
        )

        assert second_messages == first_messages
        assert first_tools == second_tools == [self._tool("end")]
        assert "【预先工具结果】" in str(first_messages[-1]["content"])
        execute_tool.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_partial_prefetch_failure_only_hides_successful_tools(
        self,
    ) -> None:
        self.client.runtime_config = _make_runtime_config(
            prefetch_tools=["get_current_time", "weather_lookup"],
            prefetch_tools_hide=True,
        )
        execute_tool = AsyncMock(
            side_effect=["2026-07-10 12:00:00", "未找到项目 weather_lookup"]
        )
        self.client.tool_manager = SimpleNamespace(execute_tool=execute_tool)
        tools = [
            self._tool("get_current_time"),
            self._tool("weather_lookup"),
            self._tool("end"),
        ]

        first_messages, first_tools = await self.client._maybe_prefetch_tools(
            [{"role": "system", "content": "system"}], tools, "chat"
        )
        second_messages, second_tools = await self.client._maybe_prefetch_tools(
            first_messages, tools, "chat"
        )

        expected_tools = [self._tool("weather_lookup"), self._tool("end")]
        assert first_tools == second_tools == expected_tools
        assert second_messages == first_messages
        assert "get_current_time" in str(first_messages[-1]["content"])
        assert "weather_lookup" not in str(first_messages[-1]["content"])
        assert execute_tool.await_count == 2

    @pytest.mark.asyncio
    async def test_failed_prefetch_is_attempted_once_per_request_context(
        self,
    ) -> None:
        self.client.runtime_config = _make_runtime_config(
            prefetch_tools=["weather_lookup"],
            prefetch_tools_hide=True,
        )
        execute_tool = AsyncMock(side_effect=RuntimeError("temporary failure"))
        self.client.tool_manager = SimpleNamespace(execute_tool=execute_tool)
        messages = [{"role": "system", "content": "system"}]
        tools = [self._tool("weather_lookup"), self._tool("end")]

        async with RequestContext(request_type="private"):
            first_messages, first_tools = await self.client._maybe_prefetch_tools(
                messages, tools, "chat"
            )
            second_messages, second_tools = await self.client._maybe_prefetch_tools(
                first_messages, tools, "chat"
            )

        assert first_messages == second_messages == messages
        assert first_tools == second_tools == tools
        execute_tool.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_request_model_can_skip_prefetch_already_attempted_by_ask(
        self,
    ) -> None:
        self.client.runtime_config = _make_runtime_config(
            prefetch_tools=["weather_lookup"],
            prefetch_tools_hide=True,
        )
        execute_tool = AsyncMock(side_effect=RuntimeError("must not execute"))
        self.client.tool_manager = SimpleNamespace(
            execute_tool=execute_tool,
            maybe_merge_agent_tools=lambda _call_type, tools: tools,
        )
        self.client._filter_tools_for_runtime_config = lambda tools: tools
        requester = AsyncMock(return_value={"choices": []})
        self.client._requester = SimpleNamespace(request=requester)
        messages = [{"role": "system", "content": "system"}]
        tools = [self._tool("weather_lookup"), self._tool("end")]

        await self.client.request_model(
            model_config=cast(Any, SimpleNamespace()),
            messages=messages,
            tools=tools,
            call_type="chat",
            skip_prefetch_tools=True,
        )

        execute_tool.assert_not_awaited()
        requester.assert_awaited_once()
        assert requester.await_args is not None
        assert requester.await_args.kwargs["messages"] == messages
        assert requester.await_args.kwargs["tools"] == tools


# ---------------------------------------------------------------------------
# ClientSetupMixin._is_end_only_tool_calls
# ---------------------------------------------------------------------------


class TestIsEndOnlyToolCalls:
    def setup_method(self) -> None:
        self.client = _make_client_setup_mixin()

    def _make_tool_call(self, internal_name: str) -> dict[str, Any]:
        return {"id": "c1", "function": {"name": internal_name, "arguments": "{}"}}

    def test_empty_tool_calls_returns_false(self) -> None:
        assert not self.client._is_end_only_tool_calls([], {})

    def test_single_end_call_returns_true(self) -> None:
        tool_calls = [self._make_tool_call("end")]
        api_to_internal = {"end": "end"}
        assert self.client._is_end_only_tool_calls(tool_calls, api_to_internal)

    def test_end_and_other_call_returns_false(self) -> None:
        tool_calls = [self._make_tool_call("end"), self._make_tool_call("send_message")]
        api_to_internal = {"end": "end", "send_message": "send_message"}
        assert not self.client._is_end_only_tool_calls(tool_calls, api_to_internal)

    def test_non_end_call_returns_false(self) -> None:
        tool_calls = [self._make_tool_call("send_message")]
        api_to_internal = {"send_message": "send_message"}
        assert not self.client._is_end_only_tool_calls(tool_calls, api_to_internal)

    def test_api_name_mapped_to_end(self) -> None:
        """Test that API name -> internal 'end' mapping works."""
        tool_calls = [self._make_tool_call("end_encoded")]
        api_to_internal = {"end_encoded": "end"}
        assert self.client._is_end_only_tool_calls(tool_calls, api_to_internal)


# ---------------------------------------------------------------------------
# ClientSetupMixin._extract_message_excerpt
# ---------------------------------------------------------------------------


class TestExtractMessageExcerpt:
    def setup_method(self) -> None:
        self.client = _make_client_setup_mixin()

    def test_plain_text_returned(self) -> None:
        result = self.client._extract_message_excerpt("Hello world")
        assert result == "Hello world"

    def test_content_tag_extracted(self) -> None:
        result = self.client._extract_message_excerpt(
            "<content>important text</content>"
        )
        assert result == "important text"

    def test_long_text_truncated_to_120(self) -> None:
        long_text = "a" * 200
        result = self.client._extract_message_excerpt(long_text)
        assert len(result) <= 120
        assert result.endswith("...")

    def test_empty_content_returns_placeholder(self) -> None:
        result = self.client._extract_message_excerpt("   ")
        assert result == "(无文本内容)"

    def test_html_entities_unescaped_in_content_tag(self) -> None:
        result = self.client._extract_message_excerpt(
            "<content>&lt;b&gt;text&lt;/b&gt;</content>"
        )
        assert "<b>" in result

    def test_multiple_spaces_collapsed(self) -> None:
        result = self.client._extract_message_excerpt("hello    world")
        assert result == "hello world"

    def test_exactly_120_chars_no_ellipsis(self) -> None:
        text = "a" * 120
        result = self.client._extract_message_excerpt(text)
        assert not result.endswith("...")
        assert len(result) == 120


# ---------------------------------------------------------------------------
# ClientSetupMixin._filter_tools_for_runtime_config
# ---------------------------------------------------------------------------


class TestFilterToolsForRuntimeConfig:
    def setup_method(self) -> None:
        self.client = _make_client_setup_mixin()

    def _make_tool(self, name: str) -> dict[str, Any]:
        return {"type": "function", "function": {"name": name}}

    def test_naga_agent_filtered_when_nagaagent_disabled(self) -> None:
        self.client.runtime_config = _make_runtime_config(nagaagent_mode_enabled=False)
        tools = [
            self._make_tool("send_message"),
            self._make_tool("naga_code_analysis_agent"),
            self._make_tool("end"),
        ]
        result = self.client._filter_tools_for_runtime_config(tools)
        names = [t["function"]["name"] for t in result]
        assert "naga_code_analysis_agent" not in names
        assert "send_message" in names
        assert "end" in names

    def test_all_tools_returned_when_nagaagent_enabled(self) -> None:
        self.client.runtime_config = _make_runtime_config(nagaagent_mode_enabled=True)
        tools = [
            self._make_tool("send_message"),
            self._make_tool("naga_code_analysis_agent"),
        ]
        result = self.client._filter_tools_for_runtime_config(tools)
        assert len(result) == 2

    def test_naga_agent_filtered_when_session_denied(self) -> None:
        from Undefined.config.models import NagaConfig

        self.client.runtime_config = _make_runtime_config(
            nagaagent_mode_enabled=True,
            naga=NagaConfig(
                mode="allowlist",
                allowed_group_ids=frozenset({100}),
            ),
        )
        tools = [
            self._make_tool("send_message"),
            self._make_tool("naga_code_analysis_agent"),
        ]
        result = self.client._filter_tools_for_runtime_config(
            tools, group_id=999, request_type="group"
        )
        names = [t["function"]["name"] for t in result]
        assert "naga_code_analysis_agent" not in names
        assert "send_message" in names

        allowed = self.client._filter_tools_for_runtime_config(
            tools, group_id=100, request_type="group"
        )
        assert len(allowed) == 2

    def test_empty_tools_list(self) -> None:
        result = self.client._filter_tools_for_runtime_config([])
        assert result == []


# ---------------------------------------------------------------------------
# ClientSetupMixin.set_knowledge_manager
# ---------------------------------------------------------------------------


class TestSetKnowledgeManager:
    def test_sets_knowledge_manager(self) -> None:
        client = _make_client_setup_mixin()
        mock_manager = MagicMock()
        client.set_knowledge_manager(mock_manager)
        assert client._knowledge_manager is mock_manager

    def test_can_set_none(self) -> None:
        client = _make_client_setup_mixin()
        client.set_knowledge_manager(None)
        assert client._knowledge_manager is None


# ---------------------------------------------------------------------------
# ClientSetupMixin.set_cognitive_service
# ---------------------------------------------------------------------------


class TestSetCognitiveService:
    def test_sets_cognitive_service(self) -> None:
        client = _make_client_setup_mixin()
        mock_service = MagicMock()
        mock_prompt_builder = MagicMock()
        client._prompt_builder = mock_prompt_builder

        client.set_cognitive_service(mock_service)

        assert client._cognitive_service is mock_service
        mock_prompt_builder.set_cognitive_service.assert_called_once_with(mock_service)

    def test_can_set_none_cognitive_service(self) -> None:
        client = _make_client_setup_mixin()
        client._prompt_builder = MagicMock()

        client.set_cognitive_service(None)
        assert client._cognitive_service is None

    def test_updates_prompt_builder(self) -> None:
        client = _make_client_setup_mixin()
        mock_service = MagicMock()
        mock_service.enabled = True
        mock_prompt_builder = MagicMock()
        client._prompt_builder = mock_prompt_builder

        client.set_cognitive_service(mock_service)
        mock_prompt_builder.set_cognitive_service.assert_called_with(mock_service)


# ---------------------------------------------------------------------------
# ClientSetupMixin.set_meme_service
# ---------------------------------------------------------------------------


class TestSetMemeService:
    def test_sets_meme_service(self) -> None:
        client = _make_client_setup_mixin()
        mock_registry = MagicMock()
        client.attachment_registry = mock_registry

        mock_service = MagicMock()
        mock_service.resolve_global_image_sync = MagicMock()
        mock_service.resolve_global_image = MagicMock()

        client.set_meme_service(mock_service)

        assert client._meme_service is mock_service
        mock_registry.set_global_image_resolver.assert_called_once()
        mock_registry.set_global_image_resolver_async.assert_called_once()

    def test_none_service_clears_resolvers(self) -> None:
        client = _make_client_setup_mixin()
        mock_registry = MagicMock()
        client.attachment_registry = mock_registry

        client.set_meme_service(None)

        assert client._meme_service is None
        mock_registry.set_global_image_resolver.assert_called_once_with(None)
        mock_registry.set_global_image_resolver_async.assert_called_once_with(None)


# ---------------------------------------------------------------------------
# ClientSetupMixin.set_queue_manager
# ---------------------------------------------------------------------------


class TestSetQueueManager:
    def test_sets_queue_manager(self) -> None:
        client = _make_client_setup_mixin()
        mock_qm = MagicMock()
        client.set_queue_manager(mock_qm)
        assert client._queue_manager is mock_qm

    def test_none_queue_manager_not_set(self) -> None:
        client = _make_client_setup_mixin()
        client.set_queue_manager(None)
        assert client._queue_manager is None

    def test_duplicate_set_is_ignored(self) -> None:
        client = _make_client_setup_mixin()
        first_qm = MagicMock()
        second_qm = MagicMock()
        client.set_queue_manager(first_qm)
        client.set_queue_manager(second_qm)
        # Second call should be ignored
        assert client._queue_manager is first_qm
