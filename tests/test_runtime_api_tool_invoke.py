from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any, cast

import pytest
from aiohttp import web
from aiohttp.web_response import Response

from Undefined.api import RuntimeAPIContext, RuntimeAPIServer
from Undefined.api._helpers import _validate_callback_url


def _json(response: Response) -> Any:
    text = response.text
    assert text is not None
    return json.loads(text)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tool_schema(name: str, description: str = "") -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description or f"Tool {name}",
            "parameters": {"type": "object", "properties": {}},
        },
    }


class _FakeToolRegistry:
    def get_tools_schema(self) -> list[dict[str, Any]]:
        return [
            _make_tool_schema("get_current_time"),
            _make_tool_schema("end"),
            _make_tool_schema("messages.send_message"),
            _make_tool_schema("scheduler.create_schedule_task"),
            _make_tool_schema("mcp.server.tool"),
        ]


class _FakeAgentRegistry:
    def get_agents_schema(self) -> list[dict[str, Any]]:
        return [
            _make_tool_schema("web_agent"),
            _make_tool_schema("code_agent"),
        ]


class _FakeToolManager:
    async def execute_tool(
        self, name: str, args: dict[str, Any], context: dict[str, Any]
    ) -> str:
        return f"executed:{name}"


def _make_api_cfg(
    *,
    tool_invoke_enabled: bool = True,
    tool_invoke_expose: str = "tools+toolsets",
    tool_invoke_allowlist: list[str] | None = None,
    tool_invoke_denylist: list[str] | None = None,
    tool_invoke_timeout: int = 120,
    tool_invoke_callback_timeout: int = 10,
) -> SimpleNamespace:
    return SimpleNamespace(
        enabled=True,
        host="127.0.0.1",
        port=8788,
        auth_key="testkey",
        openapi_enabled=True,
        tool_invoke_enabled=tool_invoke_enabled,
        tool_invoke_expose=tool_invoke_expose,
        tool_invoke_allowlist=tool_invoke_allowlist or [],
        tool_invoke_denylist=tool_invoke_denylist or [],
        tool_invoke_timeout=tool_invoke_timeout,
        tool_invoke_callback_timeout=tool_invoke_callback_timeout,
    )


def _make_server(
    api_cfg: SimpleNamespace | None = None,
) -> RuntimeAPIServer:
    if api_cfg is None:
        api_cfg = _make_api_cfg()

    context = RuntimeAPIContext(
        config_getter=lambda: SimpleNamespace(api=api_cfg),
        onebot=SimpleNamespace(connection_status=lambda: {}),
        ai=SimpleNamespace(
            memory_storage=None,
            tool_registry=_FakeToolRegistry(),
            agent_registry=_FakeAgentRegistry(),
            tool_manager=_FakeToolManager(),
            runtime_config=SimpleNamespace(),
        ),
        command_dispatcher=SimpleNamespace(),
        queue_manager=SimpleNamespace(snapshot=lambda: {}),
        history_manager=SimpleNamespace(),
        sender=SimpleNamespace(),
    )
    return RuntimeAPIServer(context, host="127.0.0.1", port=8788)


def _make_request(
    query: dict[str, str] | None = None,
    json_body: dict[str, Any] | None = None,
    remote: str = "127.0.0.1",
) -> web.Request:
    ns = SimpleNamespace(
        query=query or {},
        remote=remote,
        scheme="http",
        host=f"{remote}:8788",
    )
    if json_body is not None:

        async def _json() -> dict[str, Any]:
            return json_body

        ns.json = _json
    return cast(web.Request, cast(Any, ns))


# ---------------------------------------------------------------------------
# _validate_callback_url tests
# ---------------------------------------------------------------------------


def test_callback_url_allows_http() -> None:
    assert _validate_callback_url("http://example.com/hook") is None
    assert _validate_callback_url("http://localhost:8000/hook") is None


def test_callback_url_allows_https() -> None:
    assert _validate_callback_url("https://example.com/hook") is None


def test_callback_url_rejects_bad_scheme() -> None:
    err = _validate_callback_url("ftp://example.com/file")
    assert err is not None
    assert "http" in err


def test_callback_url_rejects_private_ip() -> None:
    assert _validate_callback_url("http://127.0.0.1:9000/hook") is not None
    assert _validate_callback_url("http://192.168.1.1/hook") is not None
    assert _validate_callback_url("http://10.0.0.1/hook") is not None
    assert _validate_callback_url("http://[::1]/hook") is not None


# ---------------------------------------------------------------------------
# _get_filtered_tools tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tools_list_disabled_returns_403() -> None:
    server = _make_server(_make_api_cfg(tool_invoke_enabled=False))
    request = _make_request()
    response = await server._tools_list_handler(request)
    assert response.status == 403


@pytest.mark.asyncio
async def test_tools_list_expose_tools_only() -> None:
    server = _make_server(_make_api_cfg(tool_invoke_expose="tools"))
    response = await server._tools_list_handler(_make_request())
    payload = _json(response)
    names = {t["function"]["name"] for t in payload["tools"]}
    # 基础工具：get_current_time, end（无点号且非 agent）
    assert "get_current_time" in names
    assert "end" in names
    # 工具集和 agent 不应出现
    assert "messages.send_message" not in names
    assert "web_agent" not in names
    assert "mcp.server.tool" not in names


@pytest.mark.asyncio
async def test_tools_list_expose_toolsets_only() -> None:
    server = _make_server(_make_api_cfg(tool_invoke_expose="toolsets"))
    response = await server._tools_list_handler(_make_request())
    payload = _json(response)
    names = {t["function"]["name"] for t in payload["tools"]}
    assert "messages.send_message" in names
    assert "scheduler.create_schedule_task" in names
    assert "get_current_time" not in names
    assert "web_agent" not in names
    assert "mcp.server.tool" not in names


@pytest.mark.asyncio
async def test_tools_list_expose_tools_plus_toolsets() -> None:
    server = _make_server(_make_api_cfg(tool_invoke_expose="tools+toolsets"))
    response = await server._tools_list_handler(_make_request())
    payload = _json(response)
    names = {t["function"]["name"] for t in payload["tools"]}
    assert "get_current_time" in names
    assert "messages.send_message" in names
    assert "web_agent" not in names
    assert "mcp.server.tool" not in names


@pytest.mark.asyncio
async def test_tools_list_expose_agents_only() -> None:
    server = _make_server(_make_api_cfg(tool_invoke_expose="agents"))
    response = await server._tools_list_handler(_make_request())
    payload = _json(response)
    names = {t["function"]["name"] for t in payload["tools"]}
    assert "web_agent" in names
    assert "code_agent" in names
    assert "get_current_time" not in names


@pytest.mark.asyncio
async def test_tools_list_expose_all() -> None:
    server = _make_server(_make_api_cfg(tool_invoke_expose="all"))
    response = await server._tools_list_handler(_make_request())
    payload = _json(response)
    names = {t["function"]["name"] for t in payload["tools"]}
    assert "get_current_time" in names
    assert "messages.send_message" in names
    assert "web_agent" in names
    assert "mcp.server.tool" in names


@pytest.mark.asyncio
async def test_tools_list_denylist_filters() -> None:
    server = _make_server(
        _make_api_cfg(
            tool_invoke_expose="all",
            tool_invoke_denylist=["web_agent", "end"],
        )
    )
    response = await server._tools_list_handler(_make_request())
    payload = _json(response)
    names = {t["function"]["name"] for t in payload["tools"]}
    assert "web_agent" not in names
    assert "end" not in names
    assert "get_current_time" in names


@pytest.mark.asyncio
async def test_tools_list_allowlist_overrides_expose() -> None:
    server = _make_server(
        _make_api_cfg(
            tool_invoke_expose="tools",
            tool_invoke_allowlist=["web_agent", "get_current_time"],
        )
    )
    response = await server._tools_list_handler(_make_request())
    payload = _json(response)
    names = {t["function"]["name"] for t in payload["tools"]}
    # allowlist 覆盖 expose，所以 agent 也能出现
    assert names == {"web_agent", "get_current_time"}


@pytest.mark.asyncio
async def test_tools_list_denylist_overrides_allowlist() -> None:
    server = _make_server(
        _make_api_cfg(
            tool_invoke_allowlist=["get_current_time", "end"],
            tool_invoke_denylist=["end"],
        )
    )
    response = await server._tools_list_handler(_make_request())
    payload = _json(response)
    names = {t["function"]["name"] for t in payload["tools"]}
    assert "end" not in names
    assert "get_current_time" in names


# ---------------------------------------------------------------------------
# _tools_invoke_handler tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invoke_disabled_returns_403() -> None:
    server = _make_server(_make_api_cfg(tool_invoke_enabled=False))
    request = _make_request(
        json_body={
            "tool_name": "get_current_time",
            "args": {},
        }
    )
    response = await server._tools_invoke_handler(request)
    assert response.status == 403


@pytest.mark.asyncio
async def test_invoke_missing_tool_name() -> None:
    server = _make_server()
    request = _make_request(json_body={"args": {}})
    response = await server._tools_invoke_handler(request)
    assert response.status == 400
    payload = _json(response)
    assert "tool_name" in payload["error"]


@pytest.mark.asyncio
async def test_invoke_args_not_dict() -> None:
    server = _make_server()
    request = _make_request(
        json_body={
            "tool_name": "get_current_time",
            "args": "not_a_dict",
        }
    )
    response = await server._tools_invoke_handler(request)
    assert response.status == 400
    payload = _json(response)
    assert "args" in payload["error"]


@pytest.mark.asyncio
async def test_invoke_tool_not_available() -> None:
    server = _make_server()
    request = _make_request(
        json_body={
            "tool_name": "nonexistent_tool",
            "args": {},
        }
    )
    response = await server._tools_invoke_handler(request)
    assert response.status == 404


@pytest.mark.asyncio
async def test_invoke_sync_success() -> None:
    server = _make_server()
    request = _make_request(
        json_body={
            "tool_name": "get_current_time",
            "args": {"format": "iso"},
        }
    )
    response = await server._tools_invoke_handler(request)
    assert response.status == 200
    payload = _json(response)
    assert payload["ok"] is True
    assert payload["tool_name"] == "get_current_time"
    assert payload["result"] == "executed:get_current_time"
    assert "request_id" in payload
    assert "duration_ms" in payload


@pytest.mark.asyncio
async def test_invoke_tool_uses_runtime_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = _make_server(_make_api_cfg(tool_invoke_timeout=7))
    original_wait_for = asyncio.wait_for
    seen: dict[str, float] = {}

    async def _wait_for(awaitable: Any, timeout: float) -> Any:
        seen["timeout"] = timeout
        return await original_wait_for(awaitable, timeout)

    monkeypatch.setattr("Undefined.api.routes.tools.asyncio.wait_for", _wait_for)

    payload = await server._execute_tool_invoke(
        request_id="req-tool",
        tool_name="get_current_time",
        args={},
        body_context=None,
        timeout=7,
    )

    assert payload["ok"] is True
    assert seen["timeout"] == 7.0


@pytest.mark.asyncio
async def test_invoke_agent_bypasses_runtime_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = _make_server(_make_api_cfg(tool_invoke_timeout=7))
    original_wait_for = asyncio.wait_for
    seen: dict[str, float] = {}

    async def _wait_for(awaitable: Any, timeout: float) -> Any:
        seen["timeout"] = timeout
        return await original_wait_for(awaitable, timeout)

    monkeypatch.setattr("Undefined.api.routes.tools.asyncio.wait_for", _wait_for)

    payload = await server._execute_tool_invoke(
        request_id="req-agent",
        tool_name="web_agent",
        args={},
        body_context=None,
        timeout=7,
    )

    assert payload["ok"] is True
    assert "timeout" not in seen


@pytest.mark.asyncio
async def test_invoke_with_context() -> None:
    server = _make_server()
    request = _make_request(
        json_body={
            "tool_name": "get_current_time",
            "args": {},
            "context": {
                "request_type": "group",
                "group_id": 12345,
                "user_id": 67890,
                "sender_id": 67890,
            },
        }
    )
    response = await server._tools_invoke_handler(request)
    assert response.status == 200
    payload = _json(response)
    assert payload["ok"] is True


@pytest.mark.asyncio
async def test_invoke_callback_bad_url_rejected() -> None:
    server = _make_server()
    request = _make_request(
        json_body={
            "tool_name": "get_current_time",
            "args": {},
            "callback": {
                "enabled": True,
                "url": "ftp://evil.example.com/hook",
            },
        }
    )
    response = await server._tools_invoke_handler(request)
    assert response.status == 400
    payload = _json(response)
    assert "http" in payload["error"]


@pytest.mark.asyncio
async def test_invoke_callback_missing_url_rejected() -> None:
    server = _make_server()
    request = _make_request(
        json_body={
            "tool_name": "get_current_time",
            "args": {},
            "callback": {"enabled": True},
        }
    )
    response = await server._tools_invoke_handler(request)
    assert response.status == 400
    payload = _json(response)
    assert "url" in payload["error"].lower()


@pytest.mark.asyncio
async def test_invoke_callback_accepted() -> None:
    server = _make_server()
    request = _make_request(
        json_body={
            "tool_name": "get_current_time",
            "args": {},
            "callback": {
                "enabled": True,
                "url": "https://webhook.example.com/hook",
                "headers": {"X-Secret": "abc"},
            },
        }
    )
    response = await server._tools_invoke_handler(request)
    assert response.status == 200
    payload = _json(response)
    assert payload["ok"] is True
    assert payload["status"] == "accepted"
    assert "request_id" in payload


# ---------------------------------------------------------------------------
# OpenAPI spec includes tool invoke paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_openapi_spec_includes_tool_invoke_paths() -> None:
    server = _make_server()
    request = _make_request()
    response = await server._openapi_handler(request)
    spec = _json(response)
    assert "/api/v1/tools" in spec["paths"]
    assert "/api/v1/tools/invoke" in spec["paths"]
