from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from aiohttp import web

from Undefined.api import RuntimeAPIContext, RuntimeAPIServer


@pytest.mark.asyncio
async def test_runtime_meme_list_handler_supports_query_modes() -> None:
    meme_service = SimpleNamespace(
        enabled=True,
        default_query_mode="hybrid",
        search_memes=AsyncMock(
            return_value={
                "ok": True,
                "count": 1,
                "query_mode": "semantic",
                "keyword_query": "",
                "semantic_query": "表达很无语的猫猫表情包",
                "sort": "use_count",
                "items": [
                    {
                        "uid": "pic_mode001",
                        "description": "无语猫猫",
                        "enabled": True,
                        "pinned": False,
                        "is_animated": False,
                        "created_at": "2026-04-03T12:00:00",
                        "updated_at": "2026-04-03T12:00:00",
                        "use_count": 5,
                        "score": 0.9,
                        "keyword_score": 0.0,
                        "semantic_score": 0.9,
                        "rerank_score": None,
                    }
                ],
            }
        ),
        list_memes=AsyncMock(),
    )
    context = RuntimeAPIContext(
        config_getter=lambda: SimpleNamespace(),
        onebot=SimpleNamespace(),
        ai=SimpleNamespace(memory_storage=SimpleNamespace(count=lambda: 0)),
        command_dispatcher=SimpleNamespace(),
        queue_manager=SimpleNamespace(),
        history_manager=SimpleNamespace(),
        meme_service=meme_service,
    )
    server = RuntimeAPIServer(context, host="127.0.0.1", port=8788)
    request = cast(
        web.Request,
        cast(
            Any,
            SimpleNamespace(
                query={
                    "query_mode": "semantic",
                    "semantic_query": "表达很无语的猫猫表情包",
                    "sort": "use_count",
                    "top_k": "5",
                },
            ),
        ),
    )

    response = await server._meme_list_handler(request)
    payload = json.loads(response.text or "{}")

    assert payload["query_mode"] == "semantic"
    assert payload["total"] is None
    assert payload["window_total"] == 1
    assert payload["total_exact"] is False
    assert payload["sort"] == "use_count"
    assert payload["items"][0]["uid"] == "pic_mode001"
    meme_service.search_memes.assert_awaited_once_with(
        "",
        query_mode="semantic",
        keyword_query=None,
        semantic_query="表达很无语的猫猫表情包",
        top_k=200,
        include_disabled=True,
        sort="use_count",
    )
    meme_service.list_memes.assert_not_called()
