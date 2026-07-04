from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from Undefined.config.search import (
    SEARCH_TOOL_FIRECRAWL,
    SEARCH_TOOL_GROK,
    SEARCH_TOOL_SEARXNG,
)
from Undefined.skills.agents.runner import _filter_tools_for_runtime_config
from Undefined.skills.agents.runner.context import (
    _build_web_agent_search_priority_prompt,
)
from Undefined.skills.agents.web_agent.tools.firecrawl_search import (
    handler as firecrawl_handler,
)


def _runtime_config(**overrides: Any) -> SimpleNamespace:
    data: dict[str, Any] = {
        "firecrawl_search_enabled": True,
        "firecrawl_api_key": "",
        "firecrawl_base_url": "https://api.firecrawl.dev",
        "search_priority": [
            SEARCH_TOOL_GROK,
            SEARCH_TOOL_FIRECRAWL,
            SEARCH_TOOL_SEARXNG,
        ],
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def _response(method: str, url: str, payload: dict[str, Any]) -> httpx.Response:
    return httpx.Response(200, json=payload, request=httpx.Request(method, url))


def test_firecrawl_search_schema_uses_query_and_num_results() -> None:
    config_path = (
        Path("src")
        / "Undefined"
        / "skills"
        / "agents"
        / "web_agent"
        / "tools"
        / "firecrawl_search"
        / "config.json"
    )
    schema = json.loads(config_path.read_text(encoding="utf-8"))
    parameters = schema["function"]["parameters"]

    assert schema["function"]["name"] == SEARCH_TOOL_FIRECRAWL
    assert parameters["required"] == ["query"]
    assert "query" in parameters["properties"]
    assert "num_results" in parameters["properties"]


@pytest.mark.asyncio
async def test_firecrawl_search_requires_query() -> None:
    result = await firecrawl_handler.execute(
        {},
        {"runtime_config": _runtime_config()},
    )

    assert result == "搜索关键词不能为空"


@pytest.mark.asyncio
async def test_firecrawl_search_returns_disabled_when_switch_is_off() -> None:
    result = await firecrawl_handler.execute(
        {"query": "example search"},
        {"runtime_config": _runtime_config(firecrawl_search_enabled=False)},
    )

    assert result == "Firecrawl 搜索功能未启用（search.firecrawl.enabled=false）"


@pytest.mark.asyncio
async def test_firecrawl_search_keyless_request_and_formats_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, Any] = {}

    async def fake_request_with_retry(
        method: str,
        url: str,
        **kwargs: Any,
    ) -> httpx.Response:
        seen["method"] = method
        seen["url"] = url
        seen["kwargs"] = kwargs
        return _response(
            method,
            url,
            {
                "success": True,
                "data": {
                    "web": [
                        {
                            "url": "https://example.com/a",
                            "title": "Example A",
                            "description": "First result",
                            "position": 1,
                        }
                    ]
                },
            },
        )

    monkeypatch.setattr(
        firecrawl_handler,
        "request_with_retry",
        fake_request_with_retry,
    )

    result = await firecrawl_handler.execute(
        {"query": "example search", "num_results": 3},
        {"runtime_config": _runtime_config(), "request_id": "req-1"},
    )

    assert seen["method"] == "POST"
    assert seen["url"] == "https://api.firecrawl.dev/v2/search"
    assert seen["kwargs"]["json_data"] == {"query": "example search", "limit": 3}
    assert seen["kwargs"]["headers"]["Content-Type"] == "application/json"
    assert "Authorization" not in seen["kwargs"]["headers"]
    assert "Example A" in result
    assert "https://example.com/a" in result
    assert "First result" in result


@pytest.mark.asyncio
async def test_firecrawl_search_sends_bearer_when_api_key_is_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, Any] = {}

    async def fake_request_with_retry(
        method: str,
        url: str,
        **kwargs: Any,
    ) -> httpx.Response:
        seen["headers"] = kwargs["headers"]
        return _response(method, url, {"success": True, "data": {"web": []}})

    monkeypatch.setattr(
        firecrawl_handler,
        "request_with_retry",
        fake_request_with_retry,
    )

    result = await firecrawl_handler.execute(
        {"query": "example search", "num_results": 99},
        {
            "runtime_config": _runtime_config(
                firecrawl_api_key="fc-test",
                firecrawl_base_url="https://firecrawl.internal/",
            )
        },
    )

    assert seen["headers"]["Authorization"] == "Bearer fc-test"
    assert result == "Firecrawl 搜索未返回结果"


@pytest.mark.asyncio
async def test_firecrawl_search_reports_rate_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_request_with_retry(
        method: str,
        url: str,
        **_kwargs: Any,
    ) -> httpx.Response:
        response = httpx.Response(429, request=httpx.Request(method, url))
        raise httpx.HTTPStatusError(
            "too many requests",
            request=response.request,
            response=response,
        )

    monkeypatch.setattr(
        firecrawl_handler,
        "request_with_retry",
        fake_request_with_retry,
    )

    result = await firecrawl_handler.execute(
        {"query": "example search"},
        {"runtime_config": _runtime_config()},
    )

    assert "限流" in result


def test_runner_filters_firecrawl_search_for_web_agent_when_disabled() -> None:
    tools = [
        {"function": {"name": SEARCH_TOOL_GROK}},
        {"function": {"name": SEARCH_TOOL_FIRECRAWL}},
        {"function": {"name": SEARCH_TOOL_SEARXNG}},
    ]

    filtered = _filter_tools_for_runtime_config(
        "web_agent",
        tools,
        SimpleNamespace(
            grok_search_enabled=True,
            firecrawl_search_enabled=False,
        ),
    )

    assert [tool["function"]["name"] for tool in filtered] == [
        SEARCH_TOOL_GROK,
        SEARCH_TOOL_SEARXNG,
    ]


def test_web_agent_priority_prompt_uses_available_enabled_tools_only() -> None:
    tools = [
        {"function": {"name": SEARCH_TOOL_FIRECRAWL}},
        {"function": {"name": SEARCH_TOOL_SEARXNG}},
        {"function": {"name": "crawl_webpage"}},
    ]

    prompt = _build_web_agent_search_priority_prompt(
        SimpleNamespace(
            search_priority=[
                SEARCH_TOOL_GROK,
                SEARCH_TOOL_FIRECRAWL,
                SEARCH_TOOL_SEARXNG,
            ]
        ),
        tools,
    )

    assert "firecrawl_search > web_search" in prompt
    assert "grok_search >" not in prompt
