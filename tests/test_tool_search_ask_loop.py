"""主 AI Tool Search 投影与执行防线集成测试。"""

from __future__ import annotations

import copy
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

from Undefined.ai.client import AIClient
from Undefined.config.models import ChatModelConfig


def _tool(name: str, description: str = "") -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description or name,
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    }


def _tool_call(call_id: str, name: str, arguments: str = "{}") -> dict[str, Any]:
    return {
        "id": call_id,
        "function": {"name": name, "arguments": arguments},
    }


def _llm_tool_calls(*tool_calls: dict[str, Any]) -> dict[str, Any]:
    return {
        "choices": [
            {
                "message": {
                    "content": "",
                    "tool_calls": list(tool_calls),
                }
            }
        ]
    }


def _schema_names(schemas: list[dict[str, Any]]) -> set[str]:
    return {str(schema.get("function", {}).get("name") or "") for schema in schemas}


def _build_client(
    *,
    llm_responses: list[dict[str, Any]],
    execute_tool: Any,
    tool_search_enabled: bool = True,
    filter_tools: Any = None,
    schemas: list[dict[str, Any]] | None = None,
    prefetch_tools: list[str] | None = None,
    prefetch_tools_hide: bool = True,
) -> Any:
    client: Any = object.__new__(AIClient)
    client.runtime_config = cast(
        Any,
        SimpleNamespace(
            log_thinking=False,
            ai_request_max_retries=0,
            missing_tool_call_retries=0,
            tool_search_enabled=tool_search_enabled,
            tool_search_always_loaded=["send_message", "end"],
            tool_search_max_results=5,
            prefetch_tools=list(prefetch_tools or []),
            prefetch_tools_hide=prefetch_tools_hide,
        ),
    )
    if schemas is None:
        schemas = [
            _tool("end"),
            _tool("send_message"),
            _tool("web_agent", "Search the web"),
            _tool("info_agent", "Look up structured information"),
        ]
    build_messages = AsyncMock(return_value=[{"role": "user", "content": "hello"}])
    client._prompt_builder = cast(
        Any,
        SimpleNamespace(build_messages=build_messages, end_summaries=[]),
    )
    client.tool_manager = cast(
        Any,
        SimpleNamespace(
            get_openai_tools=lambda: schemas,
            execute_tool=execute_tool,
        ),
    )
    client.agent_registry = cast(
        Any,
        SimpleNamespace(
            get_agents_schema=lambda: [_tool("web_agent"), _tool("info_agent")]
        ),
    )
    client._filter_tools_for_runtime_config = (
        filter_tools if filter_tools is not None else lambda tools, **_kwargs: tools
    )
    client._get_runtime_config = cast(Any, lambda: client.runtime_config)
    client.model_selector = cast(Any, SimpleNamespace(wait_ready=AsyncMock()))
    client.chat_config = ChatModelConfig(
        api_url="https://api.openai.com/v1",
        api_key="sk-test",
        model_name="chat-model",
        max_tokens=1024,
    )
    client._find_chat_config_by_name = lambda _name: client.chat_config
    client._search_wrapper = None
    client._end_summary_storage = cast(Any, None)
    client._send_private_message_callback = None
    client._send_image_callback = None
    client.memory_storage = None
    client._knowledge_manager = None
    client._cognitive_service = None
    client._meme_service = None
    client._crawl4ai_capabilities = SimpleNamespace(
        available=False,
        error=None,
        proxy_config_available=False,
    )

    submit_calls: list[dict[str, Any]] = []

    async def _submit_queued_llm_call(**kwargs: Any) -> dict[str, Any]:
        submit_calls.append(copy.deepcopy(kwargs))
        index = len(submit_calls) - 1
        if index >= len(llm_responses):
            raise RuntimeError("unexpected extra model call")
        return llm_responses[index]

    client.submit_queued_llm_call = AsyncMock(side_effect=_submit_queued_llm_call)
    client._submit_calls = submit_calls
    client._build_messages_mock = build_messages
    return client


@pytest.mark.asyncio
async def test_tool_search_loads_schema_only_for_the_next_model_round() -> None:
    executed: list[str] = []

    async def _execute_tool(
        name: str, args: dict[str, Any], context: dict[str, Any]
    ) -> str:
        _ = args
        executed.append(name)
        if name == "end":
            context["conversation_ended"] = True
            return "ended"
        return f"executed {name}"

    client = _build_client(
        execute_tool=_execute_tool,
        llm_responses=[
            _llm_tool_calls(
                _tool_call(
                    "call_search",
                    "tool_search",
                    '{"query":"select:web_agent"}',
                )
            ),
            _llm_tool_calls(_tool_call("call_web", "web_agent")),
            _llm_tool_calls(_tool_call("call_end", "end")),
        ],
    )

    assert await AIClient.ask(client, "hello") == ""

    first_names = _schema_names(client._submit_calls[0]["tools"])
    second_names = _schema_names(client._submit_calls[1]["tools"])
    third_names = _schema_names(client._submit_calls[2]["tools"])
    assert first_names == {"send_message", "end", "tool_search"}
    assert second_names == {"send_message", "end", "tool_search", "web_agent"}
    assert third_names == second_names
    assert executed == ["web_agent", "end"]

    prompt_kwargs = client._build_messages_mock.await_args.kwargs
    assert prompt_kwargs["deferred_tool_names"] == ("info_agent", "web_agent")


@pytest.mark.asyncio
async def test_tool_search_rejects_target_tool_called_in_the_search_round() -> None:
    executed: list[str] = []

    async def _execute_tool(
        name: str, args: dict[str, Any], context: dict[str, Any]
    ) -> str:
        _ = args
        executed.append(name)
        if name == "end":
            context["conversation_ended"] = True
        return "ok"

    client = _build_client(
        execute_tool=_execute_tool,
        llm_responses=[
            _llm_tool_calls(
                _tool_call(
                    "call_search",
                    "tool_search",
                    '{"query":"select:web_agent"}',
                ),
                _tool_call("call_guessed", "web_agent"),
            ),
            _llm_tool_calls(_tool_call("call_end", "end")),
        ],
    )

    assert await AIClient.ask(client, "hello") == ""

    assert executed == ["end"]
    assert "web_agent" in _schema_names(client._submit_calls[1]["tools"])
    rejected = [
        message
        for message in client._submit_calls[1]["messages"]
        if message.get("tool_call_id") == "call_guessed"
    ]
    assert len(rejected) == 1
    assert "当前未加载或不可用" in str(rejected[0]["content"])
    tool_result_ids = [
        message.get("tool_call_id")
        for message in client._submit_calls[1]["messages"]
        if message.get("role") == "tool"
    ]
    assert tool_result_ids == ["call_search", "call_guessed"]


@pytest.mark.asyncio
async def test_end_is_rejected_when_co_called_with_an_unloaded_tool() -> None:
    executed: list[str] = []

    async def _execute_tool(
        name: str, args: dict[str, Any], context: dict[str, Any]
    ) -> str:
        _ = args
        executed.append(name)
        if name == "end":
            context["conversation_ended"] = True
        return "ok"

    client = _build_client(
        execute_tool=_execute_tool,
        llm_responses=[
            _llm_tool_calls(
                _tool_call("call_guessed", "web_agent"),
                _tool_call("call_rejected_end", "end"),
            ),
            _llm_tool_calls(_tool_call("call_end", "end")),
        ],
    )

    assert await AIClient.ask(client, "hello") == ""

    assert executed == ["end"]
    first_round_results = [
        message
        for message in client._submit_calls[1]["messages"]
        if message.get("role") == "tool"
    ]
    assert [message.get("tool_call_id") for message in first_round_results] == [
        "call_guessed",
        "call_rejected_end",
    ]
    assert "end 不得与其他工具同轮调用" in str(first_round_results[1]["content"])


@pytest.mark.asyncio
async def test_tool_search_catalog_is_built_after_runtime_filtering() -> None:
    async def _execute_tool(
        name: str, args: dict[str, Any], context: dict[str, Any]
    ) -> str:
        _ = args
        if name == "end":
            context["conversation_ended"] = True
        return "ok"

    def _filter_tools(
        tools: list[dict[str, Any]], **_kwargs: Any
    ) -> list[dict[str, Any]]:
        return [schema for schema in tools if _schema_names([schema]) != {"web_agent"}]

    client = _build_client(
        execute_tool=_execute_tool,
        filter_tools=_filter_tools,
        llm_responses=[
            _llm_tool_calls(
                _tool_call(
                    "call_search",
                    "tool_search",
                    '{"query":"select:web_agent"}',
                )
            ),
            _llm_tool_calls(_tool_call("call_end", "end")),
        ],
    )

    assert await AIClient.ask(client, "hello") == ""

    prompt_kwargs = client._build_messages_mock.await_args.kwargs
    assert prompt_kwargs["deferred_tool_names"] == ("info_agent",)
    tool_result = [
        message
        for message in client._submit_calls[1]["messages"]
        if message.get("tool_call_id") == "call_search"
    ][0]
    assert '"not_found":["web_agent"]' in str(tool_result["content"])


@pytest.mark.asyncio
async def test_disabled_tool_search_preserves_full_tool_list() -> None:
    async def _execute_tool(
        name: str, args: dict[str, Any], context: dict[str, Any]
    ) -> str:
        _ = args
        if name == "end":
            context["conversation_ended"] = True
        return "ok"

    client = _build_client(
        execute_tool=_execute_tool,
        tool_search_enabled=False,
        llm_responses=[_llm_tool_calls(_tool_call("call_end", "end"))],
    )

    assert await AIClient.ask(client, "hello") == ""

    assert _schema_names(client._submit_calls[0]["tools"]) == {
        "send_message",
        "end",
        "web_agent",
        "info_agent",
    }
    assert client._build_messages_mock.await_args.kwargs["deferred_tool_names"] is None


@pytest.mark.asyncio
async def test_prefetch_result_persists_when_tool_search_is_disabled() -> None:
    executed: list[str] = []

    async def _execute_tool(
        name: str, args: dict[str, Any], context: dict[str, Any]
    ) -> str:
        _ = args
        executed.append(name)
        if name == "end":
            context["conversation_ended"] = True
        return f"result:{name}"

    client = _build_client(
        execute_tool=_execute_tool,
        tool_search_enabled=False,
        prefetch_tools=["web_agent"],
        llm_responses=[
            _llm_tool_calls(_tool_call("call_send", "send_message")),
            _llm_tool_calls(_tool_call("call_end", "end")),
        ],
    )

    assert await AIClient.ask(client, "hello") == ""

    assert executed == ["web_agent", "send_message", "end"]
    for submit_call in client._submit_calls:
        assert "web_agent" not in _schema_names(submit_call["tools"])
        prefetch_messages = [
            message
            for message in submit_call["messages"]
            if str(message.get("content") or "").startswith("【预先工具结果】")
        ]
        assert len(prefetch_messages) == 1
        assert "result:web_agent" in str(prefetch_messages[0]["content"])


@pytest.mark.asyncio
async def test_prefetch_result_persists_after_tool_search_name_collision() -> None:
    executed: list[str] = []

    async def _execute_tool(
        name: str, args: dict[str, Any], context: dict[str, Any]
    ) -> str:
        _ = args
        executed.append(name)
        if name == "end":
            context["conversation_ended"] = True
        return f"result:{name}"

    client = _build_client(
        execute_tool=_execute_tool,
        schemas=[
            _tool("end"),
            _tool("send_message"),
            _tool("web_agent", "Search the web"),
            _tool("tool_search", "Real registered tool"),
        ],
        prefetch_tools=["web_agent"],
        llm_responses=[
            _llm_tool_calls(_tool_call("call_send", "send_message")),
            _llm_tool_calls(_tool_call("call_end", "end")),
        ],
    )

    assert await AIClient.ask(client, "hello") == ""

    assert executed == ["web_agent", "send_message", "end"]
    assert client._build_messages_mock.await_args.kwargs["deferred_tool_names"] is None
    for submit_call in client._submit_calls:
        assert _schema_names(submit_call["tools"]) == {
            "end",
            "send_message",
            "tool_search",
        }
        assert (
            sum(
                str(message.get("content") or "").startswith("【预先工具结果】")
                for message in submit_call["messages"]
            )
            == 1
        )


@pytest.mark.asyncio
async def test_loaded_tools_are_reset_for_each_ask() -> None:
    async def _execute_tool(
        name: str, args: dict[str, Any], context: dict[str, Any]
    ) -> str:
        _ = args
        if name == "end":
            context["conversation_ended"] = True
        return "ok"

    search_call = _llm_tool_calls(
        _tool_call(
            "call_search",
            "tool_search",
            '{"query":"select:web_agent"}',
        )
    )
    client = _build_client(
        execute_tool=_execute_tool,
        llm_responses=[
            search_call,
            _llm_tool_calls(_tool_call("call_end_1", "end")),
            search_call,
            _llm_tool_calls(_tool_call("call_end_2", "end")),
        ],
    )

    assert await AIClient.ask(client, "first") == ""
    assert await AIClient.ask(client, "second") == ""

    initial_names = {"send_message", "end", "tool_search"}
    assert _schema_names(client._submit_calls[0]["tools"]) == initial_names
    assert _schema_names(client._submit_calls[2]["tools"]) == initial_names
