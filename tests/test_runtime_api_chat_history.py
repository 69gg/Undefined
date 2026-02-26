from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any, cast

import pytest
from aiohttp import web

from Undefined.api import RuntimeAPIContext, RuntimeAPIServer


class _DummyHistoryManager:
    def get_recent_private(self, user_id: int, count: int) -> list[dict[str, Any]]:
        _ = user_id, count
        return [
            {
                "display_name": "system",
                "message": "你好",
                "timestamp": "2026-02-25 22:00:00",
            },
            {
                "display_name": "Bot",
                "message": "你好，我在。",
                "timestamp": "2026-02-25 22:00:01",
            },
        ]


@pytest.mark.asyncio
async def test_runtime_chat_history_endpoint_returns_role_mapped_items() -> None:
    context = RuntimeAPIContext(
        config_getter=lambda: SimpleNamespace(
            api=SimpleNamespace(
                enabled=True,
                host="127.0.0.1",
                port=8788,
                auth_key="changeme",
                openapi_enabled=True,
            ),
            superadmin_qq=10001,
            bot_qq=20002,
        ),
        onebot=SimpleNamespace(connection_status=lambda: {}),
        ai=SimpleNamespace(memory_storage=SimpleNamespace(count=lambda: 0)),
        command_dispatcher=SimpleNamespace(parse_command=lambda _text: None),
        queue_manager=SimpleNamespace(snapshot=lambda: {}),
        history_manager=_DummyHistoryManager(),
    )
    server = RuntimeAPIServer(context, host="127.0.0.1", port=8788)

    request = cast(
        web.Request,
        cast(
            Any,
            SimpleNamespace(
                query={"limit": "2"},
            ),
        ),
    )
    response = await server._chat_history_handler(request)
    payload_text = response.text
    assert payload_text is not None
    payload = json.loads(payload_text)
    assert payload["virtual_user_id"] == 42
    assert payload["count"] == 2
    assert payload["items"][0]["role"] == "user"
    assert payload["items"][0]["content"] == "你好"
    assert payload["items"][1]["role"] == "bot"
    assert payload["items"][1]["content"] == "你好，我在。"
