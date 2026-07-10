"""Tool Search 与 Responses 多轮传输状态的交叉测试。"""

from __future__ import annotations

from typing import Any, cast

import httpx
import pytest
from openai import AsyncOpenAI, BadRequestError

from Undefined.ai.llm import ModelRequester
from Undefined.ai.tool_search import ToolSearchSession
from Undefined.config.models import ChatModelConfig
from Undefined.token_usage_storage import TokenUsageStorage


class _FakeUsageStorage:
    async def record(self, _usage: Any) -> None:
        return None


class _FakeResponsesAPI:
    def __init__(self, responses: list[dict[str, Any] | Exception]) -> None:
        self.calls: list[dict[str, Any]] = []
        self._responses = list(responses)

    async def create(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(dict(kwargs))
        if not self._responses:
            raise AssertionError("fake responses exhausted")
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class _FakeClient:
    def __init__(self, responses: list[dict[str, Any] | Exception]) -> None:
        self.responses = _FakeResponsesAPI(responses)


def _tool(
    name: str,
    *,
    description: str,
    properties: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties or {},
                "additionalProperties": False,
            },
        },
    }


def _tool_names(request: dict[str, Any]) -> set[str]:
    return {
        str(tool.get("name") or "")
        for tool in request.get("tools", [])
        if isinstance(tool, dict)
    }


def _build_session() -> ToolSearchSession:
    return ToolSearchSession(
        [
            _tool("send_message", description="Send a message"),
            _tool("end", description="End the conversation"),
            _tool(
                "web_agent",
                description="Search the web",
                properties={"query": {"type": "string"}},
            ),
        ],
        always_loaded_names=["send_message", "end"],
        max_results=5,
    )


def _responses_config() -> ChatModelConfig:
    return ChatModelConfig(
        api_url="https://api.openai.com/v1",
        api_key="sk-test",
        model_name="gpt-test",
        max_tokens=512,
        api_mode="responses",
    )


def _search_response() -> dict[str, Any]:
    return {
        "id": "resp_search",
        "output": [
            {
                "type": "function_call",
                "call_id": "call_search",
                "name": "tool_search",
                "arguments": '{"query":"select:web_agent"}',
            }
        ],
        "usage": {"input_tokens": 3, "output_tokens": 2, "total_tokens": 5},
    }


def _completed_response(response_id: str) -> dict[str, Any]:
    return {
        "id": response_id,
        "output": [
            {
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": "done"}],
            }
        ],
        "usage": {"input_tokens": 4, "output_tokens": 2, "total_tokens": 6},
    }


def _missing_call_error() -> BadRequestError:
    message = "No tool call found for function call output with call_id call_search."
    request = httpx.Request("POST", "https://api.example.com/v1/responses")
    response = httpx.Response(400, request=request)
    return BadRequestError(
        message,
        response=response,
        body={
            "error": {
                "message": message,
                "type": "invalid_request_error",
                "param": "input",
                "code": None,
            }
        },
    )


async def _run_search_round(
    requester: ModelRequester,
    config: ChatModelConfig,
    session: ToolSearchSession,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    user_message = {"role": "user", "content": "find current information"}
    first = await requester.request(
        model_config=config,
        messages=[user_message],
        max_tokens=128,
        call_type="chat",
        tools=session.request_tools(),
    )
    assistant_message = cast(dict[str, Any], first["choices"][0]["message"])
    search_result = session.execute({"query": "select:web_agent"})
    messages = [
        user_message,
        assistant_message,
        {
            "role": "tool",
            "tool_call_id": "call_search",
            "content": search_result,
        },
    ]
    return first, messages


@pytest.mark.asyncio
async def test_responses_dynamic_tool_schema_expands_on_previous_response_round() -> (
    None
):
    requester = ModelRequester(
        http_client=httpx.AsyncClient(),
        token_usage_storage=cast(TokenUsageStorage, _FakeUsageStorage()),
    )
    fake_client = _FakeClient([_search_response(), _completed_response("resp_done")])
    setattr(
        requester,
        "_get_openai_client_for_model",
        lambda _cfg: cast(AsyncOpenAI, fake_client),
    )
    session = _build_session()
    config = _responses_config()

    first, messages = await _run_search_round(requester, config, session)
    await requester.request(
        model_config=config,
        messages=messages,
        max_tokens=128,
        call_type="chat",
        tools=session.request_tools(),
        transport_state=first["_transport_state"],
        message_count_for_transport=len(messages),
    )

    first_request, followup_request = fake_client.responses.calls
    assert _tool_names(first_request) == {"send_message", "end", "tool_search"}
    assert _tool_names(followup_request) == {
        "send_message",
        "end",
        "tool_search",
        "web_agent",
    }
    web_tool = next(
        tool for tool in followup_request["tools"] if tool["name"] == "web_agent"
    )
    assert web_tool["parameters"]["properties"] == {"query": {"type": "string"}}
    assert followup_request["previous_response_id"] == "resp_search"
    assert followup_request["input"] == [
        {
            "type": "function_call_output",
            "call_id": "call_search",
            "output": messages[-1]["content"],
        }
    ]

    await requester._http_client.aclose()


@pytest.mark.asyncio
async def test_responses_stateless_fallback_keeps_dynamic_tool_schema() -> None:
    requester = ModelRequester(
        http_client=httpx.AsyncClient(),
        token_usage_storage=cast(TokenUsageStorage, _FakeUsageStorage()),
    )
    fake_client = _FakeClient(
        [
            _search_response(),
            _missing_call_error(),
            _completed_response("resp_replayed"),
        ]
    )
    setattr(
        requester,
        "_get_openai_client_for_model",
        lambda _cfg: cast(AsyncOpenAI, fake_client),
    )
    session = _build_session()
    config = _responses_config()

    first, messages = await _run_search_round(requester, config, session)
    result = await requester.request(
        model_config=config,
        messages=messages,
        max_tokens=128,
        call_type="chat",
        tools=session.request_tools(),
        transport_state=first["_transport_state"],
        message_count_for_transport=len(messages),
    )

    incremental_request = fake_client.responses.calls[1]
    replay_request = fake_client.responses.calls[2]
    expanded_names = {"send_message", "end", "tool_search", "web_agent"}
    assert incremental_request["previous_response_id"] == "resp_search"
    assert _tool_names(incremental_request) == expanded_names
    assert "previous_response_id" not in replay_request
    assert _tool_names(replay_request) == expanded_names
    assert [item["type"] for item in replay_request["input"]] == [
        "message",
        "function_call",
        "function_call_output",
    ]
    assert replay_request["input"][1]["name"] == "tool_search"
    assert replay_request["input"][2]["call_id"] == "call_search"
    assert result["_transport_state"] == {
        "api_mode": "responses",
        "previous_response_id": "resp_replayed",
        "tool_result_start_index": len(messages),
        "stateless_replay": True,
    }

    await requester._http_client.aclose()
