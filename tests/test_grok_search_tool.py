from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from Undefined.skills.agents.runner import _filter_tools_for_runtime_config
from Undefined.skills.agents.web_agent.tools.grok_search import handler as grok_handler


def test_grok_search_system_prompt_uses_provided_time_and_search_rules() -> None:
    prompt = grok_handler._build_grok_search_system_prompt(
        datetime(2026, 5, 30, 12, 34, 56, tzinfo=timezone.utc)
    )

    assert "2026-05-30T12:34:56+00:00" in prompt
    assert "不要以模型内部时间为准" in prompt
    assert "必须先调用搜索" in prompt
    assert "多个搜索工具" in prompt
    assert "不可胡编乱造" in prompt
    assert "必须给出来源" in prompt


def test_grok_search_schema_requires_natural_language_search_request() -> None:
    config_path = (
        Path("src")
        / "Undefined"
        / "skills"
        / "agents"
        / "web_agent"
        / "tools"
        / "grok_search"
        / "config.json"
    )
    schema = json.loads(config_path.read_text(encoding="utf-8"))
    parameters = schema["function"]["parameters"]

    assert parameters["required"] == ["search_request"]
    assert "search_request" in parameters["properties"]
    assert (
        "自然语言详细说明搜索内容和回答要求"
        in parameters["properties"]["search_request"]["description"]
    )
    assert "不要只给关键词" in schema["function"]["description"]
    assert "不要主动把范围写死" in schema["function"]["description"]
    assert (
        "不要主动添加用户未要求的硬性范围"
        in parameters["properties"]["search_request"]["description"]
    )


@pytest.mark.asyncio
async def test_grok_search_returns_disabled_when_switch_is_off() -> None:
    ai_client = SimpleNamespace(submit_queued_llm_call=AsyncMock())

    result = await grok_handler.execute(
        {"query": "latest inference model releases"},
        {
            "runtime_config": SimpleNamespace(
                grok_search_enabled=False,
                grok_model=SimpleNamespace(),
            ),
            "ai_client": ai_client,
        },
    )

    assert result == "Grok 搜索功能未启用（search.grok_search_enabled=false）"
    ai_client.submit_queued_llm_call.assert_not_awaited()


@pytest.mark.asyncio
async def test_grok_search_returns_message_content_from_dict_response() -> None:
    ai_client = SimpleNamespace(
        submit_queued_llm_call=AsyncMock(
            return_value={
                "choices": [
                    {
                        "message": {
                            "content": "这里是搜索结果摘要。",
                            "citations": [
                                {
                                    "title": "Example Source",
                                    "url": "https://example.com/article",
                                }
                            ],
                        }
                    }
                ]
            }
        )
    )
    grok_model = SimpleNamespace(
        api_url="https://grok.example/v1",
        api_key="sk-grok",
        model_name="grok-4-search",
        max_tokens=4096,
    )

    result = await grok_handler.execute(
        {
            "search_request": (
                "请搜索 2026 年最新 AI 芯片发布信息，重点比较发布时间、"
                "供应商、面向推理还是训练、公开性能指标和权威来源。"
            )
        },
        {
            "runtime_config": SimpleNamespace(
                grok_search_enabled=True,
                grok_model=grok_model,
            ),
            "ai_client": ai_client,
        },
    )

    assert "这里是搜索结果摘要。" in result
    assert "choices" not in result
    assert "参考链接:" not in result
    ai_client.submit_queued_llm_call.assert_awaited_once()
    kwargs = ai_client.submit_queued_llm_call.await_args.kwargs
    assert kwargs["model_config"] is grok_model
    assert kwargs["call_type"] == "agent_tool:grok_search"
    assert kwargs["messages"][0]["role"] == "system"
    assert "不要以模型内部时间为准" in kwargs["messages"][0]["content"]
    assert "必须先调用搜索" in kwargs["messages"][0]["content"]
    assert "多个搜索工具" in kwargs["messages"][0]["content"]
    assert "必须给出来源" in kwargs["messages"][0]["content"]
    assert kwargs["messages"][1] == {
        "role": "user",
        "content": (
            "请搜索 2026 年最新 AI 芯片发布信息，重点比较发布时间、"
            "供应商、面向推理还是训练、公开性能指标和权威来源。"
        ),
    }


@pytest.mark.asyncio
async def test_grok_search_returns_message_content_from_json_string_response() -> None:
    ai_client = SimpleNamespace(
        submit_queued_llm_call=AsyncMock(
            return_value=json.dumps(
                {
                    "id": "chatcmpl-test",
                    "choices": [
                        {
                            "finish_reason": "stop",
                            "index": 0,
                            "message": {"content": "JSON 字符串里的搜索摘要。"},
                        }
                    ],
                },
                ensure_ascii=False,
            )
        )
    )
    grok_model = SimpleNamespace(
        api_url="https://grok.example/v1",
        api_key="sk-grok",
        model_name="grok-4-search",
        max_tokens=4096,
    )

    result = await grok_handler.execute(
        {"search_request": "请搜索一个测试主题并返回摘要。"},
        {
            "runtime_config": SimpleNamespace(
                grok_search_enabled=True,
                grok_model=grok_model,
            ),
            "ai_client": ai_client,
        },
    )

    assert result == "JSON 字符串里的搜索摘要。"


@pytest.mark.asyncio
async def test_grok_search_returns_original_text_when_json_parse_fails() -> None:
    ai_client = SimpleNamespace(
        submit_queued_llm_call=AsyncMock(return_value="{not valid json")
    )
    grok_model = SimpleNamespace(
        api_url="https://grok.example/v1",
        api_key="sk-grok",
        model_name="grok-4-search",
        max_tokens=4096,
    )

    result = await grok_handler.execute(
        {"search_request": "请搜索一个测试主题并返回摘要。"},
        {
            "runtime_config": SimpleNamespace(
                grok_search_enabled=True,
                grok_model=grok_model,
            ),
            "ai_client": ai_client,
        },
    )

    assert result == "{not valid json"


@pytest.mark.asyncio
async def test_grok_search_keeps_legacy_query_fallback() -> None:
    ai_client = SimpleNamespace(submit_queued_llm_call=AsyncMock(return_value="ok"))
    grok_model = SimpleNamespace(
        api_url="https://grok.example/v1",
        api_key="sk-grok",
        model_name="grok-4-search",
        max_tokens=4096,
    )

    result = await grok_handler.execute(
        {"query": "请搜索 grok search 工具兼容旧 query 字段的测试资料"},
        {
            "runtime_config": SimpleNamespace(
                grok_search_enabled=True,
                grok_model=grok_model,
            ),
            "ai_client": ai_client,
        },
    )

    assert result == "ok"
    kwargs = ai_client.submit_queued_llm_call.await_args.kwargs
    assert kwargs["messages"][1]["content"] == (
        "请搜索 grok search 工具兼容旧 query 字段的测试资料"
    )


def test_runner_filters_grok_search_for_web_agent_when_disabled() -> None:
    tools = [
        {"function": {"name": "grok_search"}},
        {"function": {"name": "web_search"}},
        {"function": {"name": "crawl_webpage"}},
    ]

    filtered = _filter_tools_for_runtime_config(
        "web_agent",
        tools,
        SimpleNamespace(grok_search_enabled=False),
    )

    assert [tool["function"]["name"] for tool in filtered] == [
        "web_search",
        "crawl_webpage",
    ]


def test_runner_keeps_grok_search_for_other_agents() -> None:
    tools = [
        {"function": {"name": "grok_search"}},
        {"function": {"name": "web_search"}},
    ]

    filtered = _filter_tools_for_runtime_config(
        "info_agent",
        tools,
        SimpleNamespace(grok_search_enabled=False),
    )

    assert [tool["function"]["name"] for tool in filtered] == [
        "grok_search",
        "web_search",
    ]
