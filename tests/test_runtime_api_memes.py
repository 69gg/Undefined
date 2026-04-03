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
    record = SimpleNamespace(
        uid="pic_mode001",
        description="无语猫猫",
        auto_description="无语猫猫",
        manual_description="",
        ocr_text="",
        tags=["无语"],
        aliases=["猫猫"],
        enabled=True,
        pinned=False,
        is_animated=False,
        mime_type="image/png",
        file_size=123,
        width=100,
        height=100,
        use_count=5,
        last_used_at="",
        created_at="2026-04-03T12:00:00",
        updated_at="2026-04-03T12:00:00",
        status="ready",
        search_text="无语猫猫",
        preview_path="/tmp/preview.png",
        blob_path="/tmp/blob.png",
    )
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
                "items": [
                    {
                        "uid": "pic_mode001",
                        "score": 0.9,
                        "keyword_score": 0.0,
                        "semantic_score": 0.9,
                        "rerank_score": None,
                    }
                ],
            }
        ),
        get_record=AsyncMock(return_value=record),
        serialize_record=lambda item: {
            "uid": item.uid,
            "description": item.description,
            "enabled": item.enabled,
            "pinned": item.pinned,
            "is_animated": item.is_animated,
        },
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
                    "top_k": "5",
                },
            ),
        ),
    )

    response = await server._meme_list_handler(request)
    payload = json.loads(response.text or "{}")

    assert payload["query_mode"] == "semantic"
    assert payload["total"] == 1
    assert payload["items"][0]["uid"] == "pic_mode001"
    meme_service.search_memes.assert_awaited_once_with(
        "",
        query_mode="semantic",
        keyword_query=None,
        semantic_query="表达很无语的猫猫表情包",
        top_k=5,
        include_disabled=True,
    )
    meme_service.list_memes.assert_not_called()
