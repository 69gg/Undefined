from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any, cast

import pytest
from aiohttp import web

from Undefined.api import RuntimeAPIContext, RuntimeAPIServer


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
                reasoning_enabled=True,
                reasoning_effort="high",
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
        "reasoning_enabled": True,
        "reasoning_effort": "high",
    }
    assert payload["models"]["embedding_model"] == {
        "model_name": "text-embedding-3-small",
        "api_url": "https://api.example.com/...",
    }
