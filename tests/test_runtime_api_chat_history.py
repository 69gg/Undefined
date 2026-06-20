from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from aiohttp import web

from Undefined.api import RuntimeAPIContext, RuntimeAPIServer
from Undefined.api.routes import chat as runtime_api_chat


@pytest.fixture(autouse=True)
def _isolate_webchat_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)


class _DummyHistoryManager:
    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = [
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

    def get_recent_private(self, user_id: int, count: int) -> list[dict[str, Any]]:
        _ = user_id, count
        return self.records[-count:]

    def get_private_page(
        self,
        user_id: int,
        *,
        limit: int,
        before: int | None = None,
    ) -> tuple[list[dict[str, Any]], bool, int | None, int]:
        _ = user_id
        end = len(self.records) if before is None else before
        start = max(0, end - limit)
        return (
            self.records[start:end],
            start > 0,
            start if start > 0 else None,
            len(self.records),
        )

    async def clear_private_history(self, user_id: int) -> int:
        _ = user_id
        count = len(self.records)
        self.records = []
        return count


class _JsonRequest(SimpleNamespace):
    async def json(self) -> dict[str, object]:
        return dict(getattr(self, "_json", {}))


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
        onebot=SimpleNamespace(
            connection_status=lambda: {},
            get_image=lambda uid: None,
            get_forward_msg=AsyncMock(return_value=[]),
        ),
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
    assert isinstance(payload["items"][0]["message_id"], str)
    assert payload["items"][0]["message_id"]
    assert payload["items"][1]["role"] == "bot"
    assert payload["items"][1]["content"] == "你好，我在。"
    assert isinstance(payload["items"][1]["message_id"], str)
    assert payload["items"][1]["message_id"]
    assert payload["items"][0]["message_id"] != payload["items"][1]["message_id"]


@pytest.mark.asyncio
async def test_runtime_chat_history_endpoint_returns_stable_message_ids() -> None:
    history = _DummyHistoryManager()
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
        onebot=SimpleNamespace(
            connection_status=lambda: {},
            get_image=lambda uid: None,
            get_forward_msg=AsyncMock(return_value=[]),
        ),
        ai=SimpleNamespace(memory_storage=SimpleNamespace(count=lambda: 0)),
        command_dispatcher=SimpleNamespace(parse_command=lambda _text: None),
        queue_manager=SimpleNamespace(snapshot=lambda: {}),
        history_manager=history,
    )
    server = RuntimeAPIServer(context, host="127.0.0.1", port=8788)
    request = cast(web.Request, cast(Any, SimpleNamespace(query={"limit": "2"})))

    first_response = await server._chat_history_handler(request)
    second_response = await server._chat_history_handler(request)

    first_payload = json.loads(first_response.text or "{}")
    second_payload = json.loads(second_response.text or "{}")
    assert [item["message_id"] for item in first_payload["items"]] == [
        item["message_id"] for item in second_payload["items"]
    ]


@pytest.mark.asyncio
async def test_runtime_chat_history_endpoint_returns_attachment_refs() -> None:
    history = _DummyHistoryManager()
    history.records = [
        {
            "display_name": "Bot",
            "message": "[图片 uid=pic_abc123 name=image_1.png]",
            "timestamp": "2026-02-25 22:00:02",
            "attachments": [
                {
                    "uid": "pic_abc123",
                    "kind": "image",
                    "media_type": "image",
                    "display_name": "image_1.png",
                    "source_kind": "base64_image",
                }
            ],
        }
    ]
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
        onebot=SimpleNamespace(
            connection_status=lambda: {},
            get_image=lambda uid: None,
            get_forward_msg=AsyncMock(return_value=[]),
        ),
        ai=SimpleNamespace(
            memory_storage=SimpleNamespace(count=lambda: 0),
            attachment_registry=None,
        ),
        command_dispatcher=SimpleNamespace(parse_command=lambda _text: None),
        queue_manager=SimpleNamespace(snapshot=lambda: {}),
        history_manager=history,
    )
    server = RuntimeAPIServer(context, host="127.0.0.1", port=8788)

    response = await server._chat_history_handler(
        cast(web.Request, cast(Any, SimpleNamespace(query={"limit": "1"})))
    )
    payload = json.loads(response.text or "{}")

    attachment = payload["items"][0]["attachments"][0]
    assert attachment["uid"] == "pic_abc123"
    # media_type 规范为真正 MIME（原存储为粗分类 "image"）
    assert attachment["media_type"] == "image/png"
    assert attachment["display_name"] == "image_1.png"
    # 历史附件补充 preview_url/download_url，供客户端渲染缩略图
    assert attachment["preview_url"] == "/api/v1/chat/attachments/pic_abc123/preview"
    assert attachment["download_url"] == "/api/v1/chat/attachments/pic_abc123"


@pytest.mark.asyncio
async def test_runtime_chat_history_endpoint_returns_webchat_metadata_only_item() -> (
    None
):
    history = _DummyHistoryManager()
    history.records = [
        {
            "display_name": "Bot",
            "message": "",
            "timestamp": "2026-02-25 22:00:02",
            "webchat": {
                "display_only": True,
                "job_id": "job_1",
                "mode": "chat",
                "status": "done",
                "calls": [
                    {
                        "webchat_call_id": "call_1",
                        "name": "search",
                        "is_agent": False,
                        "status": "done",
                        "result_preview": "ok",
                        "children": [],
                    }
                ],
                "timeline": [
                    {
                        "type": "call",
                        "seq": 2,
                        "call": {
                            "webchat_call_id": "call_1",
                            "name": "search",
                            "is_agent": False,
                            "status": "done",
                            "result_preview": "ok",
                            "children": [],
                        },
                    }
                ],
                "events": [
                    {
                        "seq": 2,
                        "event": "tool_start",
                        "payload": {
                            "job_id": "job_1",
                            "tool_call_id": "call_1",
                            "name": "search",
                            "arguments_preview": '{"q":"test"}',
                            "is_agent": False,
                        },
                    },
                    {
                        "seq": 3,
                        "event": "tool_end",
                        "payload": {
                            "job_id": "job_1",
                            "tool_call_id": "call_1",
                            "name": "search",
                            "ok": True,
                            "result_preview": "ok",
                            "is_agent": False,
                        },
                    },
                ],
            },
        }
    ]
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
        onebot=SimpleNamespace(
            connection_status=lambda: {},
            get_image=lambda uid: None,
            get_forward_msg=AsyncMock(return_value=[]),
        ),
        ai=SimpleNamespace(memory_storage=SimpleNamespace(count=lambda: 0)),
        command_dispatcher=SimpleNamespace(parse_command=lambda _text: None),
        queue_manager=SimpleNamespace(snapshot=lambda: {}),
        history_manager=history,
    )
    server = RuntimeAPIServer(context, host="127.0.0.1", port=8788)

    response = await server._chat_history_handler(
        cast(web.Request, cast(Any, SimpleNamespace(query={"limit": "1"})))
    )
    payload = json.loads(response.text or "{}")

    assert payload["count"] == 1
    item = payload["items"][0]
    assert item["role"] == "bot"
    assert item["content"] == ""
    assert item["webchat"]["job_id"] == "job_1"
    assert [event["event"] for event in item["webchat"]["events"]] == [
        "tool_start",
        "tool_end",
    ]
    assert item["webchat"]["calls"][0]["webchat_call_id"] == "call_1"
    assert item["webchat"]["calls"][0]["result_preview"] == "ok"
    assert item["webchat"]["timeline"][0]["type"] == "call"
    assert item["webchat"]["timeline"][0]["call"]["webchat_call_id"] == "call_1"


@pytest.mark.asyncio
async def test_runtime_chat_history_endpoint_redacts_legacy_webchat_metadata() -> None:
    history = _DummyHistoryManager()
    history.records = [
        {
            "display_name": "Bot",
            "message": "",
            "timestamp": "2026-02-25 22:00:02",
            "webchat": {
                "display_only": True,
                "job_id": "job_1",
                "mode": "chat",
                "status": "done",
                "calls": [
                    {
                        "webchat_call_id": "call_1",
                        "name": "search",
                        "is_agent": False,
                        "status": "done",
                        "arguments_preview": ('{"api_key":"sk-legacy","q":"test"}'),
                        "result_preview": ("Authorization: Bearer legacy-token"),
                        "children": [],
                    }
                ],
                "timeline": [
                    {
                        "type": "call",
                        "seq": 2,
                        "call": {
                            "webchat_call_id": "call_1",
                            "name": "search",
                            "is_agent": False,
                            "status": "done",
                            "result_preview": "password=legacy-password",
                            "children": [],
                        },
                    }
                ],
                "events": [
                    {
                        "seq": 2,
                        "event": "tool_start",
                        "payload": {
                            "job_id": "job_1",
                            "tool_call_id": "call_1",
                            "name": "search",
                            "arguments_preview": (
                                '{"cookie":"sid=legacy-cookie","q":"test"}'
                            ),
                            "is_agent": False,
                        },
                    },
                ],
            },
        }
    ]
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
        onebot=SimpleNamespace(
            connection_status=lambda: {},
            get_image=lambda uid: None,
            get_forward_msg=AsyncMock(return_value=[]),
        ),
        ai=SimpleNamespace(memory_storage=SimpleNamespace(count=lambda: 0)),
        command_dispatcher=SimpleNamespace(parse_command=lambda _text: None),
        queue_manager=SimpleNamespace(snapshot=lambda: {}),
        history_manager=history,
    )
    server = RuntimeAPIServer(context, host="127.0.0.1", port=8788)

    response = await server._chat_history_handler(
        cast(web.Request, cast(Any, SimpleNamespace(query={"limit": "1"})))
    )
    payload = json.loads(response.text or "{}")
    dumped = json.dumps(payload["items"][0]["webchat"], ensure_ascii=False)

    assert "sk-legacy" not in dumped
    assert "legacy-token" not in dumped
    assert "legacy-password" not in dumped
    assert "legacy-cookie" not in dumped
    assert "[redacted]" in dumped


@pytest.mark.asyncio
async def test_runtime_chat_history_endpoint_supports_before_pagination() -> None:
    history = _DummyHistoryManager()
    history.records = [
        {"display_name": "system", "message": f"user {idx}", "timestamp": str(idx)}
        for idx in range(5)
    ]
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
        onebot=SimpleNamespace(
            connection_status=lambda: {},
            get_image=lambda uid: None,
            get_forward_msg=AsyncMock(return_value=[]),
        ),
        ai=SimpleNamespace(memory_storage=SimpleNamespace(count=lambda: 0)),
        command_dispatcher=SimpleNamespace(parse_command=lambda _text: None),
        queue_manager=SimpleNamespace(snapshot=lambda: {}),
        history_manager=history,
    )
    server = RuntimeAPIServer(context, host="127.0.0.1", port=8788)

    request = cast(
        web.Request,
        cast(Any, SimpleNamespace(query={"limit": "2", "before": "3"})),
    )
    response = await server._chat_history_handler(request)
    payload = json.loads(response.text or "{}")

    assert [item["content"] for item in payload["items"]] == ["user 1", "user 2"]
    assert payload["has_more"] is True
    assert payload["next_before"] == 1
    assert payload["total"] == 5


@pytest.mark.asyncio
async def test_runtime_chat_history_clear_clears_only_when_no_active_job() -> None:
    history = _DummyHistoryManager()
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
        onebot=SimpleNamespace(
            connection_status=lambda: {},
            get_image=lambda uid: None,
            get_forward_msg=AsyncMock(return_value=[]),
        ),
        ai=SimpleNamespace(
            attachment_registry=object(),
            memory_storage=SimpleNamespace(count=lambda: 0),
        ),
        command_dispatcher=SimpleNamespace(parse_command=lambda _text: None),
        queue_manager=SimpleNamespace(snapshot=lambda: {}),
        history_manager=history,
    )
    server = RuntimeAPIServer(context, host="127.0.0.1", port=8788)
    request = cast(web.Request, cast(Any, SimpleNamespace(query={})))

    response = await server._chat_history_clear_handler(request)
    payload = json.loads(response.text or "{}")

    assert payload["success"] is True
    assert payload["cleared"] == 2
    conversation = await server._chat_job_manager.conversation_store.get_conversation(
        str(payload["conversation_id"])
    )
    assert conversation is not None
    assert conversation["messages"] == []


@pytest.mark.asyncio
async def test_runtime_chat_history_clear_returns_409_for_running_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_run_webui_chat(_ctx: Any, *, text: str, send_output: Any) -> str:
        _ = text, send_output
        await asyncio.Event().wait()
        return "chat"

    history = _DummyHistoryManager()
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
        onebot=SimpleNamespace(
            connection_status=lambda: {},
            get_image=lambda uid: None,
            get_forward_msg=AsyncMock(return_value=[]),
        ),
        ai=SimpleNamespace(
            attachment_registry=object(),
            memory_storage=SimpleNamespace(count=lambda: 0),
        ),
        command_dispatcher=SimpleNamespace(),
        queue_manager=SimpleNamespace(snapshot=lambda: {}),
        history_manager=history,
    )
    monkeypatch.setattr(runtime_api_chat, "run_webui_chat", _fake_run_webui_chat)
    server = RuntimeAPIServer(context, host="127.0.0.1", port=8788)
    create_request = cast(
        web.Request,
        cast(Any, _JsonRequest(query={}, _json={"message": "hello"})),
    )
    await server._chat_job_create_handler(create_request)

    response = await server._chat_history_clear_handler(
        cast(web.Request, cast(Any, SimpleNamespace(query={})))
    )
    payload = json.loads(response.text or "{}")

    assert response.status == 409
    assert payload["error"] == "Chat job is still running"


@pytest.mark.asyncio
async def test_runtime_chat_non_stream_blocks_history_clear_until_done(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = asyncio.Event()
    release = asyncio.Event()

    async def _fake_run_webui_chat(_ctx: Any, *, text: str, send_output: Any) -> str:
        assert text == "hello"
        started.set()
        await release.wait()
        await send_output(42, "done")
        return "chat"

    history = _DummyHistoryManager()
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
        onebot=SimpleNamespace(
            connection_status=lambda: {},
            get_image=lambda uid: None,
            get_forward_msg=AsyncMock(return_value=[]),
        ),
        ai=SimpleNamespace(
            attachment_registry=object(),
            memory_storage=SimpleNamespace(count=lambda: 0),
        ),
        command_dispatcher=SimpleNamespace(),
        queue_manager=SimpleNamespace(snapshot=lambda: {}),
        history_manager=history,
    )
    monkeypatch.setattr(runtime_api_chat, "run_webui_chat", _fake_run_webui_chat)
    server = RuntimeAPIServer(context, host="127.0.0.1", port=8788)
    chat_request = cast(
        web.Request,
        cast(Any, _JsonRequest(query={}, _json={"message": "hello"})),
    )
    chat_task = asyncio.create_task(server._chat_handler(chat_request))
    await asyncio.wait_for(started.wait(), timeout=1)

    clear_response = await server._chat_history_clear_handler(
        cast(web.Request, cast(Any, SimpleNamespace(query={})))
    )
    clear_payload = json.loads(clear_response.text or "{}")

    assert clear_response.status == 409
    assert clear_payload["error"] == "Chat job is still running"

    release.set()
    chat_response = await asyncio.wait_for(chat_task, timeout=1)
    chat_payload = json.loads(cast(web.Response, chat_response).text or "{}")

    assert chat_response.status == 200
    assert chat_payload["reply"] == "done"
    assert chat_payload["messages"] == ["done"]


@pytest.mark.asyncio
async def test_runtime_chat_history_clear_returns_409_until_history_finalized() -> None:
    history = _DummyHistoryManager()
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
        onebot=SimpleNamespace(
            connection_status=lambda: {},
            get_image=lambda uid: None,
            get_forward_msg=AsyncMock(return_value=[]),
        ),
        ai=SimpleNamespace(
            attachment_registry=object(),
            memory_storage=SimpleNamespace(count=lambda: 0),
        ),
        command_dispatcher=SimpleNamespace(),
        queue_manager=SimpleNamespace(snapshot=lambda: {}),
        history_manager=history,
    )
    manager = runtime_api_chat.ChatJobManager(context)
    job = runtime_api_chat.ChatJob(
        job_id="job_finalizing",
        text="hello",
        created_at=1.0,
        updated_at=1.0,
        status="done",
        history_finalized=False,
    )
    manager._jobs[job.job_id] = job

    response = await runtime_api_chat.chat_history_clear_handler(
        context,
        manager,
        cast(web.Request, cast(Any, SimpleNamespace(query={}))),
    )
    payload = json.loads(response.text or "{}")

    assert response.status == 409
    assert payload["error"] == "Chat job is still running"
    assert history.records

    job.history_finalized = True
    job.done.set()
    response = await runtime_api_chat.chat_history_clear_handler(
        context,
        manager,
        cast(web.Request, cast(Any, SimpleNamespace(query={}))),
    )
    payload = json.loads(response.text or "{}")

    assert response.status == 200
    assert payload["success"] is True
    assert payload["cleared"] == 2
    conversation = await manager.conversation_store.get_conversation(
        str(payload["conversation_id"])
    )
    assert conversation is not None
    assert conversation["messages"] == []
