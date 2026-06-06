from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from aiohttp import web

from Undefined.api import RuntimeAPIContext, RuntimeAPIServer
from Undefined.api.routes import chat as runtime_api_chat
from Undefined.api.webchat_store import DEFAULT_WEBCHAT_CONVERSATION_ID


class _JsonRequest(SimpleNamespace):
    async def json(self) -> dict[str, object]:
        return dict(getattr(self, "_json", {}))


class _History:
    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = [
            {"display_name": "system", "message": "旧问题是什么", "timestamp": "1"},
            {"display_name": "Bot", "message": "旧答案是这个", "timestamp": "2"},
        ]

    def get_recent_private(self, user_id: int, count: int) -> list[dict[str, Any]]:
        _ = user_id
        return self.records[-count:]


def _context(history: Any | None = None) -> RuntimeAPIContext:
    return RuntimeAPIContext(
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
        ai=SimpleNamespace(
            attachment_registry=object(),
            memory_storage=SimpleNamespace(count=lambda: 0),
        ),
        command_dispatcher=SimpleNamespace(parse_command=lambda _text: None),
        queue_manager=SimpleNamespace(snapshot=lambda: {}),
        history_manager=history or _History(),
    )


@pytest.mark.asyncio
async def test_webchat_legacy_history_migrates_once_and_delete_does_not_remigrate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    server = RuntimeAPIServer(_context(), host="127.0.0.1", port=8788)
    request = cast(web.Request, cast(Any, SimpleNamespace(query={})))

    first = await server._chat_conversations_handler(request)
    payload = json.loads(first.text or "{}")
    assert [item["id"] for item in payload["conversations"]] == [
        DEFAULT_WEBCHAT_CONVERSATION_ID
    ]
    assert payload["conversations"][0]["title"].startswith("旧问题")

    delete = await server._chat_conversation_delete_handler(
        cast(
            web.Request,
            cast(
                Any,
                SimpleNamespace(
                    query={},
                    match_info={"conversation_id": DEFAULT_WEBCHAT_CONVERSATION_ID},
                ),
            ),
        )
    )
    assert delete.status == 200

    second = await server._chat_conversations_handler(request)
    payload = json.loads(second.text or "{}")
    assert payload["conversations"] == []
    assert (tmp_path / "data" / "webchat" / "legacy_private_42_migrated.json").exists()


@pytest.mark.asyncio
async def test_webchat_title_generation_uses_first_question_and_answer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    context = _context(history=SimpleNamespace(get_recent_private=lambda *_args: []))
    captured: dict[str, str] = {}

    async def _fake_generate_title(_ai: Any, question: str, answer: str) -> str:
        captured["question"] = question
        captured["answer"] = answer
        return "首问首答标题"

    monkeypatch.setattr(
        runtime_api_chat, "generate_webchat_title", _fake_generate_title
    )
    server = RuntimeAPIServer(context, host="127.0.0.1", port=8788)
    create_response = await server._chat_conversation_create_handler(
        cast(web.Request, cast(Any, _JsonRequest(query={}, _json={})))
    )
    conversation = json.loads(create_response.text or "{}")["conversation"]
    conversation_id = str(conversation["id"])

    await server._chat_job_manager.conversation_store.append_message(
        conversation_id,
        role="user",
        text_content="请解释缓存命中",
        display_name="system",
        user_name="system",
    )
    await server._chat_job_manager.conversation_store.append_message(
        conversation_id,
        role="bot",
        text_content="缓存命中依赖稳定前缀。",
        display_name="Bot",
        user_name="Bot",
    )
    await server._chat_job_manager.maybe_schedule_title_generation(conversation_id)
    task = server._chat_job_manager.conversation_store._title_tasks[conversation_id]
    await task

    updated = await server._chat_job_manager.conversation_store.get_conversation(
        conversation_id
    )
    assert captured == {
        "question": "请解释缓存命中",
        "answer": "缓存命中依赖稳定前缀。",
    }
    assert updated is not None
    assert updated["title"] == "首问首答标题"
    assert updated["title_status"] == "generated"


@pytest.mark.asyncio
async def test_webchat_manual_title_blocks_generated_overwrite(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    server = RuntimeAPIServer(
        _context(history=SimpleNamespace(get_recent_private=lambda *_args: [])),
        host="127.0.0.1",
        port=8788,
    )
    create_response = await server._chat_conversation_create_handler(
        cast(web.Request, cast(Any, _JsonRequest(query={}, _json={})))
    )
    conversation_id = str(
        json.loads(create_response.text or "{}")["conversation"]["id"]
    )
    await server._chat_job_manager.conversation_store.append_message(
        conversation_id,
        role="user",
        text_content="第一个问题",
        display_name="system",
        user_name="system",
    )
    await server._chat_job_manager.conversation_store.append_message(
        conversation_id,
        role="bot",
        text_content="第一个回答",
        display_name="Bot",
        user_name="Bot",
    )
    await server._chat_job_manager.conversation_store.rename_conversation(
        conversation_id,
        "手动标题",
    )

    await server._chat_job_manager.maybe_schedule_title_generation(conversation_id)
    updated = await server._chat_job_manager.conversation_store.get_conversation(
        conversation_id
    )

    assert updated is not None
    assert updated["title"] == "手动标题"
    assert updated["title_status"] == "manual"


@pytest.mark.asyncio
async def test_webchat_history_isolated_by_conversation_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    server = RuntimeAPIServer(
        _context(history=SimpleNamespace(get_recent_private=lambda *_args: [])),
        host="127.0.0.1",
        port=8788,
    )
    first_response = await server._chat_conversation_create_handler(
        cast(web.Request, cast(Any, _JsonRequest(query={}, _json={})))
    )
    second_response = await server._chat_conversation_create_handler(
        cast(web.Request, cast(Any, _JsonRequest(query={}, _json={})))
    )
    first_id = str(json.loads(first_response.text or "{}")["conversation"]["id"])
    second_id = str(json.loads(second_response.text or "{}")["conversation"]["id"])

    await server._chat_job_manager.conversation_store.append_message(
        first_id,
        role="user",
        text_content="第一会话消息",
        display_name="system",
        user_name="system",
    )
    await server._chat_job_manager.conversation_store.append_message(
        second_id,
        role="user",
        text_content="第二会话消息",
        display_name="system",
        user_name="system",
    )

    first_history = await server._chat_history_handler(
        cast(
            web.Request,
            cast(Any, SimpleNamespace(query={"conversation_id": first_id})),
        )
    )
    first_payload = json.loads(first_history.text or "{}")
    second_history = await server._chat_history_handler(
        cast(
            web.Request,
            cast(Any, SimpleNamespace(query={"conversation_id": second_id})),
        )
    )
    second_payload = json.loads(second_history.text or "{}")

    assert first_payload["conversation_id"] == first_id
    assert [item["content"] for item in first_payload["items"]] == ["第一会话消息"]
    assert second_payload["conversation_id"] == second_id
    assert [item["content"] for item in second_payload["items"]] == ["第二会话消息"]


@pytest.mark.asyncio
async def test_webchat_delete_and_clear_reject_while_job_running(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    server = RuntimeAPIServer(
        _context(history=SimpleNamespace(get_recent_private=lambda *_args: [])),
        host="127.0.0.1",
        port=8788,
    )
    create_response = await server._chat_conversation_create_handler(
        cast(web.Request, cast(Any, _JsonRequest(query={}, _json={})))
    )
    conversation_id = str(
        json.loads(create_response.text or "{}")["conversation"]["id"]
    )
    job = await server._chat_job_manager.create_job("hello", conversation_id)
    job.task = AsyncMock()

    delete_response = await server._chat_conversation_delete_handler(
        cast(
            web.Request,
            cast(
                Any,
                SimpleNamespace(
                    query={}, match_info={"conversation_id": conversation_id}
                ),
            ),
        )
    )
    clear_response = await server._chat_history_clear_handler(
        cast(
            web.Request,
            cast(Any, SimpleNamespace(query={"conversation_id": conversation_id})),
        )
    )

    assert delete_response.status == 409
    assert clear_response.status == 409
    assert (
        await server._chat_job_manager.conversation_store.get_conversation(
            conversation_id
        )
        is not None
    )
