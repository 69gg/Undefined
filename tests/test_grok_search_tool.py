from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from Undefined.skills.agents.runner import _filter_tools_for_runtime_config
from Undefined.skills.agents.web_agent.tools.grok_search import handler as grok_handler


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
async def test_grok_search_returns_raw_result() -> None:
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
        {"query": "请详细搜索 2026 年最新 AI 芯片发布信息"},
        {
            "runtime_config": SimpleNamespace(
                grok_search_enabled=True,
                grok_model=grok_model,
            ),
            "ai_client": ai_client,
        },
    )

    assert "这里是搜索结果摘要。" in result
    assert "参考链接:" not in result
    ai_client.submit_queued_llm_call.assert_awaited_once()
    kwargs = ai_client.submit_queued_llm_call.await_args.kwargs
    assert kwargs["model_config"] is grok_model
    assert kwargs["call_type"] == "agent_tool:grok_search"


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
