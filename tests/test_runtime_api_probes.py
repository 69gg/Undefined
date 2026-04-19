from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any, cast

import pytest
from aiohttp import web

from Undefined.api import RuntimeAPIContext, RuntimeAPIServer
from Undefined.api.routes import system as runtime_api_system


@pytest.mark.asyncio
async def test_runtime_internal_probe_includes_chat_model_transport_fields() -> None:
    context = RuntimeAPIContext(
        config_getter=lambda: SimpleNamespace(
            api=SimpleNamespace(
                enabled=True,
                host="127.0.0.1",
                port=8788,
                auth_key="changeme",
                openapi_enabled=True,
            ),
            chat_model=SimpleNamespace(
                model_name="gpt-5.4",
                api_url="https://api.example.com/v1",
                api_mode="responses",
                thinking_enabled=False,
                thinking_tool_call_compat=True,
                responses_tool_choice_compat=False,
                responses_force_stateless_replay=False,
                prompt_cache_enabled=True,
                reasoning_enabled=True,
                reasoning_effort="high",
            ),
            grok_model=SimpleNamespace(
                model_name="grok-4-search",
                api_url="https://grok.example/v1",
                thinking_enabled=False,
                prompt_cache_enabled=True,
                reasoning_enabled=True,
                reasoning_effort="low",
            ),
            embedding_model=SimpleNamespace(
                model_name="text-embedding-3-small",
                api_url="https://api.example.com/v1",
            ),
        ),
        onebot=SimpleNamespace(connection_status=lambda: {}),
        ai=SimpleNamespace(memory_storage=None),
        command_dispatcher=SimpleNamespace(),
        queue_manager=SimpleNamespace(snapshot=lambda: {}),
        history_manager=SimpleNamespace(),
    )
    server = RuntimeAPIServer(context, host="127.0.0.1", port=8788)

    request = cast(web.Request, cast(Any, SimpleNamespace()))
    response = await server._internal_probe_handler(request)
    response_text = response.text
    assert response_text is not None
    payload = json.loads(response_text)

    chat_model = payload["models"]["chat_model"]
    assert chat_model == {
        "model_name": "gpt-5.4",
        "api_url": "https://api.example.com/...",
        "api_mode": "responses",
        "thinking_enabled": False,
        "thinking_tool_call_compat": True,
        "responses_tool_choice_compat": False,
        "responses_force_stateless_replay": False,
        "prompt_cache_enabled": True,
        "reasoning_enabled": True,
        "reasoning_effort": "high",
    }
    assert payload["models"]["embedding_model"] == {
        "model_name": "text-embedding-3-small",
        "api_url": "https://api.example.com/...",
    }
    assert payload["models"]["grok_model"] == {
        "model_name": "grok-4-search",
        "api_url": "https://grok.example/...",
        "thinking_enabled": False,
        "prompt_cache_enabled": True,
        "reasoning_enabled": True,
        "reasoning_effort": "low",
    }


@pytest.mark.asyncio
async def test_runtime_internal_probe_includes_group_superadmin_queue_snapshot() -> (
    None
):
    context = RuntimeAPIContext(
        config_getter=lambda: SimpleNamespace(
            api=SimpleNamespace(
                enabled=True,
                host="127.0.0.1",
                port=8788,
                auth_key="changeme",
                openapi_enabled=True,
            ),
            chat_model=SimpleNamespace(
                model_name="gpt-5.4",
                api_url="https://api.example.com/v1",
                api_mode="responses",
                thinking_enabled=False,
                thinking_tool_call_compat=True,
                responses_tool_choice_compat=False,
                responses_force_stateless_replay=False,
                reasoning_enabled=True,
                reasoning_effort="high",
            ),
        ),
        onebot=SimpleNamespace(connection_status=lambda: {}),
        ai=SimpleNamespace(memory_storage=None),
        command_dispatcher=SimpleNamespace(),
        queue_manager=SimpleNamespace(
            snapshot=lambda: {
                "totals": {
                    "retry": 1,
                    "superadmin": 2,
                    "group_superadmin": 3,
                    "private": 4,
                    "group_mention": 5,
                    "group_normal": 6,
                    "background": 7,
                }
            }
        ),
        history_manager=SimpleNamespace(),
    )
    server = RuntimeAPIServer(context, host="127.0.0.1", port=8788)

    request = cast(web.Request, cast(Any, SimpleNamespace()))
    response = await server._internal_probe_handler(request)
    response_text = response.text
    assert response_text is not None
    payload = json.loads(response_text)

    assert payload["queues"]["totals"]["group_superadmin"] == 3


@pytest.mark.asyncio
async def test_runtime_external_probe_skips_naga_model_when_integration_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_probe_http_endpoint(**kwargs: Any) -> dict[str, Any]:
        return {
            "name": kwargs["name"],
            "status": "ok",
            "url": "https://api.example.com/...",
            "http_status": 200,
            "latency_ms": 1.0,
            "model_name": kwargs.get("model_name", ""),
        }

    async def _fake_probe_ws_endpoint(_: str) -> dict[str, Any]:
        return {
            "name": "onebot_ws",
            "status": "ok",
            "host": "127.0.0.1",
            "port": 3001,
            "latency_ms": 1.0,
        }

    monkeypatch.setattr(
        runtime_api_system, "_probe_http_endpoint", _fake_probe_http_endpoint
    )
    monkeypatch.setattr(
        runtime_api_system, "_probe_ws_endpoint", _fake_probe_ws_endpoint
    )

    context = RuntimeAPIContext(
        config_getter=lambda: SimpleNamespace(
            api=SimpleNamespace(
                enabled=True,
                host="127.0.0.1",
                port=8788,
                auth_key="changeme",
                openapi_enabled=True,
            ),
            nagaagent_mode_enabled=False,
            naga=SimpleNamespace(enabled=False),
            chat_model=SimpleNamespace(
                model_name="chat",
                api_url="https://api.example.com/v1",
                api_key="k1",
            ),
            vision_model=SimpleNamespace(
                model_name="vision",
                api_url="https://api.example.com/v1",
                api_key="k2",
            ),
            security_model=SimpleNamespace(
                model_name="security",
                api_url="https://api.example.com/v1",
                api_key="k3",
            ),
            naga_model=SimpleNamespace(
                model_name="naga",
                api_url="https://api.example.com/v1",
                api_key="k4",
            ),
            agent_model=SimpleNamespace(
                model_name="agent",
                api_url="https://api.example.com/v1",
                api_key="k5",
            ),
            grok_model=SimpleNamespace(
                model_name="grok",
                api_url="https://grok.example/v1",
                api_key="k55",
            ),
            embedding_model=SimpleNamespace(
                model_name="embed",
                api_url="https://api.example.com/v1",
                api_key="k6",
            ),
            rerank_model=SimpleNamespace(
                model_name="rerank",
                api_url="https://api.example.com/v1",
                api_key="k7",
            ),
            onebot_ws_url="ws://127.0.0.1:3001",
        ),
        onebot=SimpleNamespace(connection_status=lambda: {}),
        ai=SimpleNamespace(memory_storage=None),
        command_dispatcher=SimpleNamespace(),
        queue_manager=SimpleNamespace(snapshot=lambda: {}),
        history_manager=SimpleNamespace(),
    )
    server = RuntimeAPIServer(context, host="127.0.0.1", port=8788)

    request = cast(web.Request, cast(Any, SimpleNamespace()))
    response = await server._external_probe_handler(request)
    response_text = response.text
    assert response_text is not None
    payload = json.loads(response_text)

    naga_probe = next(
        item for item in payload["results"] if item["name"] == "naga_model"
    )
    assert naga_probe == {
        "name": "naga_model",
        "status": "skipped",
        "reason": "naga_integration_disabled",
        "model_name": "naga",
    }
    grok_probe = next(
        item for item in payload["results"] if item["name"] == "grok_model"
    )
    assert grok_probe["status"] == "ok"
    assert grok_probe["model_name"] == "grok"
