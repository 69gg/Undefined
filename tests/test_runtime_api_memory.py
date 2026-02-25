from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any, cast

import pytest
from aiohttp import web

from Undefined.api import RuntimeAPIContext, RuntimeAPIServer
from Undefined.memory import Memory


class _DummyMemoryStorage:
    def __init__(self) -> None:
        self._items = [
            Memory(uuid="m1", fact="用户喜欢猫", created_at="2026-02-25 10:00:00"),
            Memory(uuid="m2", fact="用户偏好 Python", created_at="2026-02-25 11:00:00"),
        ]

    def get_all(self) -> list[Memory]:
        return list(self._items)

    def count(self) -> int:
        return len(self._items)

    async def add(self, _fact: str) -> str:
        raise AssertionError("memory query endpoint should be read-only")

    async def update(self, _uuid: str, _fact: str) -> bool:
        raise AssertionError("memory query endpoint should be read-only")

    async def delete(self, _uuid: str) -> bool:
        raise AssertionError("memory query endpoint should be read-only")


@pytest.mark.asyncio
async def test_runtime_memory_endpoint_read_only_and_searchable() -> None:
    context = RuntimeAPIContext(
        config_getter=lambda: SimpleNamespace(
            api=SimpleNamespace(
                enabled=True,
                host="127.0.0.1",
                port=8788,
                auth_key="changeme",
                openapi_enabled=True,
            )
        ),
        onebot=SimpleNamespace(connection_status=lambda: {}),
        ai=SimpleNamespace(memory_storage=_DummyMemoryStorage()),
        command_dispatcher=SimpleNamespace(),
        queue_manager=SimpleNamespace(snapshot=lambda: {}),
        history_manager=SimpleNamespace(),
    )
    server = RuntimeAPIServer(context, host="127.0.0.1", port=8788)

    request_all = cast(web.Request, cast(Any, SimpleNamespace(query={})))
    response_all = await server._memory_handler(request_all)
    response_all_text = response_all.text
    assert response_all_text is not None
    payload_all = json.loads(response_all_text)
    assert payload_all["total"] == 2
    assert payload_all["items"][0]["uuid"] == "m1"

    request_query = cast(web.Request, cast(Any, SimpleNamespace(query={"q": "python"})))
    response_query = await server._memory_handler(request_query)
    response_query_text = response_query.text
    assert response_query_text is not None
    payload_query = json.loads(response_query_text)
    assert payload_query["total"] == 1
    assert payload_query["items"][0]["uuid"] == "m2"
