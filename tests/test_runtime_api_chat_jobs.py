from __future__ import annotations

import asyncio
import hashlib
import json
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from aiohttp import web

from Undefined.api import RuntimeAPIContext, RuntimeAPIServer
from Undefined.api.routes import chat as runtime_api_chat
from Undefined.utils import io as async_io
from Undefined.utils.paths import ensure_dir


@pytest.fixture(autouse=True)
def _isolate_webchat_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)


class _DummyTransport:
    def __init__(self, *, closing_after_writes: int | None = None) -> None:
        self._closing_after_writes = closing_after_writes
        self.write_count = 0

    def is_closing(self) -> bool:
        if self._closing_after_writes is None:
            return False
        return self.write_count >= self._closing_after_writes


class _DummyRequest(SimpleNamespace):
    async def json(self) -> dict[str, object]:
        return dict(getattr(self, "_json", {}))


class _DummyStreamResponse:
    def __init__(
        self,
        *,
        status: int,
        reason: str,
        headers: dict[str, str],
    ) -> None:
        self.status = status
        self.reason = reason
        self.headers = dict(headers)
        self.writes: list[bytes] = []
        self.eof_written = False
        self._request: Any = None

    async def prepare(self, request: web.Request) -> _DummyStreamResponse:
        self._request = request
        return self

    async def write(self, data: bytes) -> None:
        self.writes.append(data)
        transport = getattr(self._request, "transport", None)
        if isinstance(transport, _DummyTransport):
            transport.write_count += 1

    async def write_eof(self) -> None:
        self.eof_written = True


def _context() -> RuntimeAPIContext:
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
        history_manager=SimpleNamespace(add_private_message=AsyncMock()),
    )


async def _last_webchat_record(server: RuntimeAPIServer) -> dict[str, Any]:
    conversation = await server._chat_job_manager.conversation_store.get_conversation(
        "legacy-system-42"
    )
    assert conversation is not None
    messages = conversation.get("messages")
    assert isinstance(messages, list)
    assert messages
    return cast(dict[str, Any], messages[-1])


@pytest.mark.asyncio
@pytest.mark.parametrize("first_operation", ["create", "delete"])
@pytest.mark.parametrize("pre_record_user_history", [False, True])
async def test_conversation_delete_and_job_acceptance_are_serialized(
    monkeypatch: pytest.MonkeyPatch,
    first_operation: str,
    pre_record_user_history: bool,
) -> None:
    release_chat = asyncio.Event()
    chat_started = asyncio.Event()

    async def run_chat(_ctx: RuntimeAPIContext, **_kwargs: Any) -> str:
        chat_started.set()
        await release_chat.wait()
        return "chat"

    monkeypatch.setattr(runtime_api_chat, "run_webui_chat", run_chat)
    server = RuntimeAPIServer(_context(), host="127.0.0.1", port=8788)
    manager = server._chat_job_manager
    store = manager.conversation_store
    await store.ensure_ready(manager._ctx.history_manager)
    conversation = await store.create_conversation()
    conversation_id = str(conversation["id"])
    request = cast(
        web.Request,
        cast(Any, _DummyRequest(match_info={"conversation_id": conversation_id})),
    )
    # 模拟重命名/文件写入持有真实会话锁，让两种请求在同一边界排队。
    conversation_lock = store._get_lock(conversation_id)
    await conversation_lock.acquire()

    async def create() -> runtime_api_chat.ChatJob | None:
        try:
            return await manager.create_job(
                "hello",
                conversation_id,
                pre_record_user_history=pre_record_user_history,
            )
        except KeyError:
            return None

    async def delete() -> web.Response:
        return await server._chat_conversation_delete_handler(request)

    try:
        if first_operation == "create":
            creation = asyncio.create_task(create())
            await asyncio.sleep(0)
            deletion = asyncio.create_task(delete())
        else:
            deletion = asyncio.create_task(delete())
            await asyncio.sleep(0)
            creation = asyncio.create_task(create())
        await asyncio.sleep(0)
        conversation_lock.release()
        job, response = await asyncio.wait_for(
            asyncio.gather(creation, deletion), timeout=2
        )
        if first_operation == "create":
            assert job is not None
            assert response.status == 409
            assert await store.get_conversation(conversation_id) is not None
            await asyncio.wait_for(chat_started.wait(), timeout=2)
            await store.append_message(
                conversation_id,
                role="bot",
                text_content="reply",
                display_name="Bot",
                user_name="Bot",
            )
        else:
            assert response.status == 200
            assert job is None
            assert not manager._jobs
            assert not chat_started.is_set()
            assert await store.get_conversation(conversation_id) is None
    finally:
        if conversation_lock.locked():
            conversation_lock.release()
        release_chat.set()
        await server.stop()


@pytest.mark.asyncio
async def test_running_job_snapshot_contains_complete_nested_display_timeline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ready = asyncio.Event()
    release = asyncio.Event()

    async def run_chat(
        _ctx: RuntimeAPIContext,
        *,
        send_output: Any,
        webchat_event_callback: Any,
        **_kwargs: Any,
    ) -> str:
        await send_output(42, "root prefix")
        await webchat_event_callback(
            "tool_start",
            {
                "tool_call_id": "agent-tool",
                "webchat_call_id": "agent",
                "name": "web_agent",
                "is_agent": True,
                "arguments": {"password": "must-not-leak"},
            },
        )
        await send_output(42, "agent message")
        nested = {
            "tool_call_id": "search-tool",
            "webchat_call_id": "agent/search",
            "parent_webchat_call_id": "agent",
            "name": "search",
        }
        await webchat_event_callback("tool_start", nested)
        await webchat_event_callback(
            "tool_end", {**nested, "ok": True, "result": "completed search"}
        )
        ready.set()
        await release.wait()
        return "chat"

    monkeypatch.setattr(runtime_api_chat, "run_webui_chat", run_chat)
    server = RuntimeAPIServer(_context(), host="127.0.0.1", port=8788)
    manager = server._chat_job_manager
    job = await manager.create_job("hello")
    try:
        await asyncio.wait_for(ready.wait(), timeout=2)
        detail = await server._chat_job_detail_handler(
            cast(
                web.Request, cast(Any, _DummyRequest(match_info={"job_id": job.job_id}))
            )
        )
        snapshot = json.loads(detail.text or "{}")
        assert snapshot["last_seq"] == job.next_seq - 1
        assert snapshot["messages"] == ["root prefix", "agent message"]
        timeline = snapshot["current_timeline"]
        assert [item["type"] for item in timeline] == ["message", "call"]
        assert timeline[0]["content"] == "root prefix"
        agent = timeline[1]["call"]
        assert agent["webchat_call_id"] == "agent"
        assert agent["status"] == "running"
        assert [item["type"] for item in agent["timeline"]] == ["message", "call"]
        assert agent["timeline"][0]["content"] == "agent message"
        child = agent["timeline"][1]["call"]
        assert child["status"] == "done"
        assert child["result_preview"] == "completed search"
        assert agent["children"] == [child]
        assert "must-not-leak" not in json.dumps(timeline)
        assert len(snapshot["current_tool_calls"]) == 1
        assert snapshot["current_tool_calls"][0]["webchat_call_id"] == "agent"
        events, refreshed, _live = await manager.events_after_with_snapshot(
            job, snapshot["last_seq"]
        )
        assert events == []
        assert refreshed["current_timeline"] == timeline
    finally:
        release.set()
        await server.stop()


@pytest.mark.asyncio
async def test_job_snapshot_preserves_display_content_beyond_sse_replay_limit() -> None:
    manager = runtime_api_chat.ChatJobManager(_context())
    job = runtime_api_chat.ChatJob("snapshot-job", "hello", 1, 1, status="running")
    for index in range(runtime_api_chat._CHAT_JOB_EVENT_BUFFER_LIMIT + 5):
        await manager._append_event(job, "message", {"content": f"message-{index}"})
    snapshot = await manager.snapshot(job)
    timeline = snapshot["current_timeline"]
    assert len(job.events) == runtime_api_chat._CHAT_JOB_EVENT_BUFFER_LIMIT
    assert len(timeline) == runtime_api_chat._CHAT_JOB_EVENT_BUFFER_LIMIT + 5
    assert timeline[0]["content"] == "message-0"
    assert timeline[-1]["content"] == (
        f"message-{runtime_api_chat._CHAT_JOB_EVENT_BUFFER_LIMIT + 4}"
    )
    assert timeline[-1]["seq"] == snapshot["last_seq"]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["error", "cancelled"])
async def test_terminal_snapshot_finalizes_unclosed_display_calls(
    status: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = 10.0
    monkeypatch.setattr(time, "time", lambda: now)
    manager = runtime_api_chat.ChatJobManager(_context())
    job = runtime_api_chat.ChatJob("terminal-job", "hello", 1, 1, status="running")
    await manager.append_lifecycle_event(
        job,
        "tool_start",
        {"tool_call_id": "tool", "webchat_call_id": "tool", "name": "search"},
    )
    now = 12.0
    job.status = status
    manager._mark_job_finished(job)
    timeline = (await manager.snapshot(job))["current_timeline"]
    call = timeline[0]["call"]
    assert call["status"] == status
    assert call["duration_ms"] == 2000
    assert call["elapsed_ms"] == 11000
    now = 20.0
    assert timeline == runtime_api_chat._build_webchat_history_payload(job)["timeline"]


@pytest.mark.asyncio
async def test_history_finalized_is_published_only_after_job_releases_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run_chat(ctx: RuntimeAPIContext, *, text: str, send_output: Any) -> str:
        await send_output(42, "final")
        return "chat"

    title_entered = asyncio.Event()
    release_title = asyncio.Event()

    async def schedule_title(conversation_id: str) -> None:
        title_entered.set()
        await release_title.wait()

    server = RuntimeAPIServer(_context(), host="127.0.0.1", port=8788)
    manager = server._chat_job_manager
    monkeypatch.setattr(runtime_api_chat, "run_webui_chat", run_chat)
    monkeypatch.setattr(manager, "maybe_schedule_title_generation", schedule_title)
    job = await manager.create_job("first")
    detail_request = cast(
        web.Request,
        cast(Any, _DummyRequest(match_info={"job_id": job.job_id}, query={})),
    )
    events_request = cast(
        web.Request,
        cast(
            Any,
            _DummyRequest(
                match_info={"job_id": job.job_id},
                query={"format": "json"},
                headers={"Accept": "application/json"},
            ),
        ),
    )
    try:
        await asyncio.wait_for(title_entered.wait(), timeout=2.0)
        # 真实 job 已经落盘，但最终收尾仍占用会话。
        assert job.status == "done"
        assert job.history_finalized is True
        assert not job.done.is_set()
        assert await manager.has_running_job(job.conversation_id)
        assert (await manager.snapshot(job))["history_finalized"] is False
        response = await server._chat_job_detail_handler(detail_request)
        assert json.loads(response.text or "{}")["history_finalized"] is False
        events_response = await server._chat_job_events_handler(events_request)
        assert isinstance(events_response, web.Response)
        payload = json.loads(events_response.text or "{}")
        assert payload["job"]["history_finalized"] is False
        assert any(event["event"] == "done" for event in payload["events"])
        with pytest.raises(RuntimeError, match="still running"):
            await manager.create_job("too early", job.conversation_id)

        release_title.set()
        assert job.task is not None
        await asyncio.wait_for(job.task, timeout=2.0)
        assert job.done.is_set()
        assert not await manager.has_running_job(job.conversation_id)
        response = await server._chat_job_detail_handler(detail_request)
        assert json.loads(response.text or "{}")["history_finalized"] is True
        events_response = await server._chat_job_events_handler(events_request)
        assert isinstance(events_response, web.Response)
        assert (
            json.loads(events_response.text or "{}")["job"]["history_finalized"] is True
        )
        next_job = await manager.create_job("next", job.conversation_id)
        assert next_job.task is not None
        await asyncio.wait_for(next_job.task, timeout=2.0)
    finally:
        release_title.set()
        await manager.stop()


async def _store_runtime_attachment(
    attachment_id: str = "attachment123",
    *,
    name: str = "note.txt",
    content: bytes = b"runtime attachment",
) -> dict[str, Any]:
    ensure_dir(runtime_api_chat._CHAT_ATTACHMENT_BLOB_DIR)
    ensure_dir(runtime_api_chat._CHAT_ATTACHMENT_META_DIR)
    await asyncio.to_thread(
        runtime_api_chat._chat_attachment_blob_path(attachment_id).write_bytes,
        content,
    )
    metadata = runtime_api_chat._chat_attachment_response_metadata(
        {
            "id": attachment_id,
            "name": name,
            "size": len(content),
            "media_type": "text/plain",
            "kind": "file",
            "sha256": hashlib.sha256(content).hexdigest(),
            "created_at": "2026-06-08T10:00:00",
        }
    )
    await async_io.write_json(
        runtime_api_chat._chat_attachment_meta_path(attachment_id),
        metadata,
        use_lock=True,
    )
    return metadata


def _decode_sse(writes: list[bytes]) -> list[dict[str, Any]]:
    payload = b"".join(writes).decode("utf-8")
    events: list[dict[str, Any]] = []
    for block in payload.split("\n\n"):
        if not block.strip() or block.startswith(":"):
            continue
        event = "message"
        seq = 0
        data_lines: list[str] = []
        for line in block.splitlines():
            if line.startswith("id:"):
                seq = int(line[3:].strip())
            elif line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                data_lines.append(line[5:].strip())
        if data_lines:
            events.append(
                {
                    "seq": seq,
                    "event": event,
                    "payload": json.loads("\n".join(data_lines)),
                }
            )
    return events


@pytest.mark.asyncio
async def test_run_webui_chat_prompt_describes_webui_markdown_html_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, str] = {}

    class _AI:
        attachment_registry: object = object()
        memory_storage: Any = SimpleNamespace(count=lambda: 0)
        runtime_config: Any = SimpleNamespace()

        async def ask(self, question: str, **_kwargs: Any) -> str:
            captured["question"] = question
            return ""

    context = _context()
    context.ai = _AI()
    context.onebot = SimpleNamespace(
        get_image=AsyncMock(return_value=None),
        get_forward_msg=AsyncMock(return_value=[]),
    )
    context.command_dispatcher = SimpleNamespace(parse_command=lambda _text: None)

    async def _fake_register_message_attachments(**_kwargs: Any) -> Any:
        return SimpleNamespace(normalized_text="hello", attachments=[])

    monkeypatch.setattr(
        runtime_api_chat,
        "register_message_attachments",
        _fake_register_message_attachments,
    )

    mode = await runtime_api_chat.run_webui_chat(
        context,
        text="hello",
        send_output=AsyncMock(),
    )

    assert mode == "chat"
    prompt = captured["question"]
    assert "【WebUI 会话】" in prompt
    assert "WebUI 支持完整 Markdown 渲染和简单安全 HTML" in prompt
    assert (
        "复杂 HTML、包含 JS/CSS 的页面、可运行示例或较长代码必须放进 fenced code block"
        in prompt
    )
    assert "完整 HTML 页面请优先使用 ```html 代码框" in prompt
    assert "优先在当前聊天消息中直接给出" in prompt
    assert "不要为了普通代码片段调用文件生成或文件发送工具" in prompt
    assert "始终标明语言或类型" in prompt
    assert "不确定语言时使用 ```text" in prompt


@pytest.mark.asyncio
async def test_chat_job_events_after_reconnect_and_disconnect_does_not_cancel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = asyncio.Event()
    release = asyncio.Event()
    cancelled = False

    async def _fake_run_webui_chat(_ctx: Any, *, text: str, send_output: Any) -> str:
        nonlocal cancelled
        assert text == "hello"
        try:
            await send_output(42, "first")
            started.set()
            await release.wait()
            await send_output(42, "second")
            return "chat"
        except asyncio.CancelledError:
            cancelled = True
            raise

    monkeypatch.setattr(runtime_api_chat, "run_webui_chat", _fake_run_webui_chat)
    monkeypatch.setattr(web, "StreamResponse", _DummyStreamResponse)

    server = RuntimeAPIServer(_context(), host="127.0.0.1", port=8788)
    create_request = cast(
        web.Request,
        cast(Any, _DummyRequest(_json={"message": "hello"}, query={})),
    )
    create_response = await server._chat_job_create_handler(create_request)
    create_payload = json.loads(create_response.text or "{}")
    job_id = str(create_payload["job_id"])

    await asyncio.wait_for(started.wait(), timeout=1)

    first_request = cast(
        web.Request,
        cast(
            Any,
            _DummyRequest(
                match_info={"job_id": job_id},
                query={"after": "0"},
                headers={"Accept": "text/event-stream"},
                transport=_DummyTransport(closing_after_writes=1),
            ),
        ),
    )
    first_response = await server._chat_job_events_handler(first_request)
    first_events = _decode_sse(cast(_DummyStreamResponse, first_response).writes)
    assert first_events[0]["event"] == "meta"
    first_last_seq = first_events[-1]["seq"]
    assert cancelled is False

    release.set()
    detail_request = cast(
        web.Request,
        cast(Any, _DummyRequest(match_info={"job_id": job_id}, query={})),
    )
    for _ in range(20):
        detail_response = await server._chat_job_detail_handler(detail_request)
        detail_payload = json.loads(detail_response.text or "{}")
        if detail_payload["status"] == "done":
            break
        await asyncio.sleep(0.01)
    assert isinstance(detail_payload["duration_ms"], int)
    assert detail_payload["finished_at"] is not None

    second_request = cast(
        web.Request,
        cast(
            Any,
            _DummyRequest(
                match_info={"job_id": job_id},
                query={"after": str(first_last_seq)},
                headers={"Accept": "text/event-stream"},
                transport=_DummyTransport(),
            ),
        ),
    )
    second_response = await server._chat_job_events_handler(second_request)
    second_events = _decode_sse(cast(_DummyStreamResponse, second_response).writes)

    assert cancelled is False
    assert "stage" in [event["event"] for event in second_events]
    assert [event["event"] for event in second_events if event["event"] != "stage"] == [
        "message",
        "done",
    ]
    message_events = [event for event in second_events if event["event"] == "message"]
    assert message_events[0]["payload"]["content"] == "second"


@pytest.mark.asyncio
async def test_chat_job_cancel_unknown_returns_404() -> None:
    server = RuntimeAPIServer(_context(), host="127.0.0.1", port=8788)
    request = cast(
        web.Request,
        cast(Any, _DummyRequest(match_info={"job_id": "missing"}, query={})),
    )

    response = await server._chat_job_cancel_handler(request)
    payload = json.loads(response.text or "{}")

    assert response.status == 404
    assert payload["error"] == "Job not found"


@pytest.mark.asyncio
async def test_chat_jobs_are_concurrent_across_conversations_and_single_flight_per_conversation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = asyncio.Event()

    async def _fake_run_webui_chat(_ctx: Any, **_kwargs: Any) -> str:
        await release.wait()
        return "chat"

    monkeypatch.setattr(runtime_api_chat, "run_webui_chat", _fake_run_webui_chat)
    server = RuntimeAPIServer(_context(), host="127.0.0.1", port=8788)
    first = await server._chat_job_manager.conversation_store.create_conversation(
        title="first"
    )
    second = await server._chat_job_manager.conversation_store.create_conversation(
        title="second"
    )

    first_response = await server._chat_job_create_handler(
        cast(
            web.Request,
            cast(
                Any,
                _DummyRequest(
                    query={},
                    _json={
                        "conversation_id": first["id"],
                        "message": "first message",
                    },
                ),
            ),
        )
    )
    second_response = await server._chat_job_create_handler(
        cast(
            web.Request,
            cast(
                Any,
                _DummyRequest(
                    query={},
                    _json={
                        "conversation_id": second["id"],
                        "message": "second message",
                    },
                ),
            ),
        )
    )
    duplicate_response = await server._chat_job_create_handler(
        cast(
            web.Request,
            cast(
                Any,
                _DummyRequest(
                    query={},
                    _json={
                        "conversation_id": first["id"],
                        "message": "duplicate message",
                    },
                ),
            ),
        )
    )

    assert first_response.status == 202
    assert second_response.status == 202
    assert duplicate_response.status == 409

    release.set()
    await server.stop()


@pytest.mark.asyncio
async def test_chat_job_active_returns_jobs_array_and_compatible_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = asyncio.Event()

    async def _fake_run_webui_chat(_ctx: Any, **_kwargs: Any) -> str:
        await release.wait()
        return "chat"

    monkeypatch.setattr(runtime_api_chat, "run_webui_chat", _fake_run_webui_chat)
    server = RuntimeAPIServer(_context(), host="127.0.0.1", port=8788)
    first = await server._chat_job_manager.conversation_store.create_conversation()
    second = await server._chat_job_manager.conversation_store.create_conversation()
    first_job = await server._chat_job_manager.create_job("first", str(first["id"]))
    second_job = await server._chat_job_manager.create_job("second", str(second["id"]))

    response = await server._chat_job_active_handler(
        cast(web.Request, cast(Any, _DummyRequest(query={})))
    )
    payload = json.loads(response.text or "{}")
    filtered_response = await server._chat_job_active_handler(
        cast(
            web.Request,
            cast(
                Any,
                _DummyRequest(query={"conversation_id": str(second["id"])}),
            ),
        )
    )
    filtered_payload = json.loads(filtered_response.text or "{}")

    assert {item["job_id"] for item in payload["jobs"]} == {
        first_job.job_id,
        second_job.job_id,
    }
    assert payload["job"]["job_id"] == second_job.job_id
    assert [item["job_id"] for item in filtered_payload["jobs"]] == [second_job.job_id]
    assert filtered_payload["job"]["job_id"] == second_job.job_id
    release.set()
    await server.stop()


@pytest.mark.asyncio
async def test_chat_conversations_active_job_compatible_field_uses_latest_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = asyncio.Event()

    async def _fake_run_webui_chat(_ctx: Any, **_kwargs: Any) -> str:
        await release.wait()
        return "chat"

    monkeypatch.setattr(runtime_api_chat, "run_webui_chat", _fake_run_webui_chat)
    server = RuntimeAPIServer(_context(), host="127.0.0.1", port=8788)
    first = await server._chat_job_manager.conversation_store.create_conversation()
    second = await server._chat_job_manager.conversation_store.create_conversation()
    first_job = await server._chat_job_manager.create_job("first", str(first["id"]))
    second_job = await server._chat_job_manager.create_job("second", str(second["id"]))

    response = await server._chat_conversations_handler(
        cast(web.Request, cast(Any, _DummyRequest(query={})))
    )
    payload = json.loads(response.text or "{}")

    assert payload["active_job"]["job_id"] == second_job.job_id
    assert payload["active_job"]["job_id"] != first_job.job_id
    release.set()
    await server.stop()


@pytest.mark.asyncio
async def test_chat_job_create_accepts_structured_message_and_persists_references(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_text: list[str] = []

    async def _fake_run_webui_chat(_ctx: Any, *, text: str, **_kwargs: Any) -> str:
        captured_text.append(text)
        return "chat"

    monkeypatch.setattr(runtime_api_chat, "run_webui_chat", _fake_run_webui_chat)
    server = RuntimeAPIServer(_context(), host="127.0.0.1", port=8788)
    conversation = (
        await server._chat_job_manager.conversation_store.create_conversation(
            title="structured"
        )
    )
    await server._chat_job_manager.conversation_store.append_message(
        str(conversation["id"]),
        role="bot",
        text_content="可以引用的回复",
        display_name="Bot",
        user_name="Bot",
    )
    history_page = await server._chat_job_manager.conversation_store.get_history_page(
        str(conversation["id"]), limit=1, before=None
    )
    source_message_id = str(history_page.records[0]["message_id"])

    response = await server._chat_job_create_handler(
        cast(
            web.Request,
            cast(
                Any,
                _DummyRequest(
                    query={},
                    _json={
                        "conversation_id": str(conversation["id"]),
                        "message": {
                            "text": "请解释这段",
                            "references": [
                                {
                                    "kind": "message",
                                    "source_message_id": source_message_id,
                                    "selected_text": "引用片段",
                                }
                            ],
                        },
                    },
                ),
            ),
        )
    )
    payload = json.loads(response.text or "{}")

    assert response.status == 202
    assert payload["waiting_input"] is None
    detail_request = cast(
        web.Request,
        cast(Any, _DummyRequest(match_info={"job_id": payload["job_id"]}, query={})),
    )
    for _ in range(20):
        detail_response = await server._chat_job_detail_handler(detail_request)
        detail_payload = json.loads(detail_response.text or "{}")
        if detail_payload["status"] == "done":
            break
        await asyncio.sleep(0.01)
    assert captured_text == [
        f"> 引用 message:{source_message_id}\n> 引用片段\n\n请解释这段"
    ]
    request_history = (
        await server._chat_job_manager.conversation_store.get_history_page(
            str(conversation["id"]), limit=1, before=None
        )
    )
    record = request_history.records[0]
    assert record["message"] == captured_text[0]
    assert record["references"][0]["source_message_id"] == source_message_id


@pytest.mark.asyncio
async def test_chat_job_create_structured_attachment_is_not_duplicated_in_prompt_or_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    async def _fake_run_webui_chat(
        _ctx: Any,
        *,
        text: str,
        input_attachments: list[dict[str, str]],
        record_input_history: bool,
        **_kwargs: Any,
    ) -> str:
        captured["text"] = text
        captured["input_attachments"] = input_attachments
        captured["record_input_history"] = record_input_history
        return "chat"

    monkeypatch.setattr(runtime_api_chat, "run_webui_chat", _fake_run_webui_chat)
    server = RuntimeAPIServer(_context(), host="127.0.0.1", port=8788)
    conversation = (
        await server._chat_job_manager.conversation_store.create_conversation(
            title="attachment"
        )
    )
    attachment = await _store_runtime_attachment()

    response = await server._chat_job_create_handler(
        cast(
            web.Request,
            cast(
                Any,
                _DummyRequest(
                    query={},
                    _json={
                        "conversation_id": str(conversation["id"]),
                        "message": {
                            "text": "请分析附件",
                            "attachment_ids": [attachment["id"]],
                        },
                    },
                ),
            ),
        )
    )
    payload = json.loads(response.text or "{}")

    assert response.status == 202
    detail_request = cast(
        web.Request,
        cast(Any, _DummyRequest(match_info={"job_id": payload["job_id"]}, query={})),
    )
    for _ in range(20):
        detail_response = await server._chat_job_detail_handler(detail_request)
        detail_payload = json.loads(detail_response.text or "{}")
        if detail_payload["status"] == "done":
            break
        await asyncio.sleep(0.01)

    assert captured["text"] == "请分析附件"
    assert "<attachment" not in captured["text"]
    assert captured["input_attachments"][0]["uid"] == attachment["id"]
    assert captured["record_input_history"] is False
    request_history = (
        await server._chat_job_manager.conversation_store.get_history_page(
            str(conversation["id"]), limit=1, before=None
        )
    )
    record = request_history.records[0]
    assert record["message"] == "请分析附件"
    assert "<attachment" not in record["message"]
    assert record["attachments"][0]["uid"] == attachment["id"]


@pytest.mark.asyncio
async def test_chat_job_create_reuse_previous_user_message_skips_duplicate_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    async def _fake_run_webui_chat(
        _ctx: Any,
        *,
        text: str,
        record_input_history: bool,
        **_kwargs: Any,
    ) -> str:
        captured["text"] = text
        captured["record_input_history"] = record_input_history
        return "chat"

    monkeypatch.setattr(runtime_api_chat, "run_webui_chat", _fake_run_webui_chat)
    server = RuntimeAPIServer(_context(), host="127.0.0.1", port=8788)
    conversation = (
        await server._chat_job_manager.conversation_store.create_conversation(
            title="retry"
        )
    )
    await server._chat_job_manager.conversation_store.append_message(
        str(conversation["id"]),
        role="user",
        text_content="搜索今日国内国际新闻热点",
        display_name="system",
        user_name="system",
    )
    await server._chat_job_manager.conversation_store.append_message(
        str(conversation["id"]),
        role="bot",
        text_content="",
        display_name="Bot",
        user_name="Bot",
        webchat={
            "display_only": True,
            "events": [
                {
                    "seq": 1,
                    "event": "message",
                    "payload": {"content": ""},
                }
            ],
        },
    )

    response = await server._chat_job_create_handler(
        cast(
            web.Request,
            cast(
                Any,
                _DummyRequest(
                    query={},
                    _json={
                        "conversation_id": str(conversation["id"]),
                        "message": {
                            "text": "搜索今日国内国际新闻热点",
                        },
                        "reuse_previous_user_message": True,
                    },
                ),
            ),
        )
    )
    payload = json.loads(response.text or "{}")

    assert response.status == 202
    detail_request = cast(
        web.Request,
        cast(Any, _DummyRequest(match_info={"job_id": payload["job_id"]}, query={})),
    )
    for _ in range(20):
        detail_response = await server._chat_job_detail_handler(detail_request)
        detail_payload = json.loads(detail_response.text or "{}")
        if detail_payload["status"] == "done":
            break
        await asyncio.sleep(0.01)

    assert captured["text"] == "搜索今日国内国际新闻热点"
    assert captured["record_input_history"] is False
    history_page = await server._chat_job_manager.conversation_store.get_history_page(
        str(conversation["id"]),
        limit=20,
        before=None,
    )
    user_records = [
        record
        for record in history_page.records
        if str(record.get("display_name", "")).lower() != "bot"
        and str(record.get("message", "")).strip()
    ]
    assert [record["message"] for record in user_records] == [
        "搜索今日国内国际新闻热点"
    ]


@pytest.mark.asyncio
async def test_chat_job_create_reuse_previous_user_message_requires_matching_tail() -> (
    None
):
    server = RuntimeAPIServer(_context(), host="127.0.0.1", port=8788)
    conversation = (
        await server._chat_job_manager.conversation_store.create_conversation(
            title="retry mismatch"
        )
    )
    await server._chat_job_manager.conversation_store.append_message(
        str(conversation["id"]),
        role="user",
        text_content="上一条",
        display_name="system",
        user_name="system",
    )

    response = await server._chat_job_create_handler(
        cast(
            web.Request,
            cast(
                Any,
                _DummyRequest(
                    query={},
                    _json={
                        "conversation_id": str(conversation["id"]),
                        "message": {
                            "text": "另一条",
                        },
                        "reuse_previous_user_message": True,
                    },
                ),
            ),
        )
    )

    assert response.status == 400
    payload = json.loads(response.text or "{}")
    assert (
        payload["error"]
        == "reuse_previous_user_message requires a matching last user message"
    )


@pytest.mark.asyncio
async def test_requires_action_event_is_preserved_for_runtime_stream_and_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_run_webui_chat(
        _ctx: Any,
        *,
        webchat_event_callback: Any,
        **_kwargs: Any,
    ) -> str:
        await webchat_event_callback(
            "requires_action",
            {
                "action_id": "approval-1",
                "kind": "confirm",
                "detail": "需要确认",
                "secret": "should-redact",
            },
        )
        return "chat"

    monkeypatch.setattr(runtime_api_chat, "run_webui_chat", _fake_run_webui_chat)
    server = RuntimeAPIServer(_context(), host="127.0.0.1", port=8788)
    job = await server._chat_job_manager.create_job("需要人工确认")

    detail_request = cast(
        web.Request,
        cast(Any, _DummyRequest(match_info={"job_id": job.job_id}, query={})),
    )
    for _ in range(20):
        detail_response = await server._chat_job_detail_handler(detail_request)
        detail_payload = json.loads(detail_response.text or "{}")
        if detail_payload["status"] == "done":
            break
        await asyncio.sleep(0.01)

    events_request = cast(
        web.Request,
        cast(
            Any,
            _DummyRequest(
                match_info={"job_id": job.job_id},
                query={"after": "0", "format": "json"},
                headers={"Accept": "application/json"},
            ),
        ),
    )
    events_response = cast(
        web.Response, await server._chat_job_events_handler(events_request)
    )
    events_payload = json.loads(events_response.text or "{}")
    requires_action = [
        item for item in events_payload["events"] if item["event"] == "requires_action"
    ]

    assert requires_action
    assert requires_action[0]["payload"]["action_id"] == "approval-1"
    assert requires_action[0]["payload"]["secret"] == "[redacted]"
    request_history = (
        await server._chat_job_manager.conversation_store.get_history_page(
            job.conversation_id, limit=1, before=None
        )
    )
    webchat_events = request_history.records[0]["webchat"]["events"]
    assert any(item["event"] == "requires_action" for item in webchat_events)


@pytest.mark.asyncio
async def test_chat_job_create_rejects_empty_structured_message() -> None:
    server = RuntimeAPIServer(_context(), host="127.0.0.1", port=8788)

    response = await server._chat_job_create_handler(
        cast(
            web.Request,
            cast(
                Any,
                _DummyRequest(
                    query={},
                    _json={"message": {"text": "  ", "attachment_ids": []}},
                ),
            ),
        )
    )
    payload = json.loads(response.text or "{}")

    assert response.status == 400
    assert payload["error"] == "message is required"


@pytest.mark.asyncio
async def test_chat_job_create_rejects_unknown_structured_attachment() -> None:
    server = RuntimeAPIServer(_context(), host="127.0.0.1", port=8788)

    response = await server._chat_job_create_handler(
        cast(
            web.Request,
            cast(
                Any,
                _DummyRequest(
                    query={},
                    _json={
                        "message": {
                            "text": "hello",
                            "attachment_ids": ["missing-attachment"],
                        }
                    },
                ),
            ),
        )
    )
    payload = json.loads(response.text or "{}")

    assert response.status == 404
    assert payload["error"] == "Attachment not found"


@pytest.mark.asyncio
async def test_chat_job_cancelled_error_event_is_appended_once() -> None:
    server = RuntimeAPIServer(_context(), host="127.0.0.1", port=8788)
    manager = server._chat_job_manager
    job = runtime_api_chat.ChatJob(
        job_id="job-cancel",
        text="hello",
        created_at=0.0,
        updated_at=0.0,
    )

    await asyncio.gather(*(manager._append_cancelled_event_once(job) for _ in range(8)))

    cancelled_events = [
        event
        for event in job.events
        if event.event == "error" and event.payload.get("error") == "cancelled"
    ]
    assert len(cancelled_events) == 1


@pytest.mark.asyncio
async def test_chat_job_history_write_failure_rolls_back_creation_and_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = RuntimeAPIServer(_context(), host="127.0.0.1", port=8788)
    manager = server._chat_job_manager
    await manager.conversation_store.ensure_ready()
    conversation = await manager.conversation_store.ensure_default_conversation()
    conversation_id = str(conversation["id"])
    history_path = manager.conversation_store._path_for(conversation_id)
    original_disk = history_path.read_bytes()
    original_write = async_io.write_json_sync
    fail_once = True

    def write_json(file_path: Path | str, data: Any, use_lock: bool = True) -> None:
        nonlocal fail_once
        if Path(file_path) == history_path and data.get("messages") and fail_once:
            fail_once = False
            raise OSError("history disk unavailable")
        original_write(file_path, data, use_lock)

    run_chat = AsyncMock(return_value="chat")
    monkeypatch.setattr(async_io, "write_json_sync", write_json)
    monkeypatch.setattr(runtime_api_chat, "run_webui_chat", run_chat)

    def request() -> web.Request:
        return cast(
            web.Request,
            cast(
                Any,
                _DummyRequest(
                    _json={
                        "conversation_id": conversation_id,
                        "message": {"text": "hello"},
                    }
                ),
            ),
        )

    with pytest.raises(OSError, match="history disk unavailable"):
        await server._chat_job_create_handler(request())

    assert not manager._jobs
    assert await manager.get_active_job(conversation_id) is None
    page = await manager.conversation_store.get_history_page(
        conversation_id, limit=50, before=None
    )
    assert page.total == 0
    assert history_path.read_bytes() == original_disk
    run_chat.assert_not_awaited()

    retry = await server._chat_job_create_handler(request())
    assert retry.status == 202
    job = await manager.get_job(str(json.loads(retry.text or "{}")["job_id"]))
    assert job is not None and job.task is not None
    await asyncio.wait_for(job.task, timeout=2)
    page = await manager.conversation_store.get_history_page(
        conversation_id, limit=50, before=None
    )
    assert [record["message"] for record in page.records] == ["hello"]
    assert len(json.loads(history_path.read_text(encoding="utf-8"))["messages"]) == 1
    assert await manager.clear_history_when_idle(conversation_id) == 1
    await server.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint", ["job", "sync", "sse"])
async def test_chat_stop_rejects_new_jobs_while_existing_job_finishes(
    endpoint: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    started = asyncio.Event()
    cancelling = asyncio.Event()
    release = asyncio.Event()
    calls: list[str] = []

    async def run_chat(_ctx: Any, *, text: str, **_kwargs: Any) -> str:
        calls.append(text)
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelling.set()
            await release.wait()
        return "chat"

    monkeypatch.setattr(runtime_api_chat, "run_webui_chat", run_chat)
    server = RuntimeAPIServer(_context(), host="127.0.0.1", port=8788)
    manager = server._chat_job_manager
    job = await manager.create_job("old")
    other = await manager.conversation_store.create_conversation()
    await asyncio.wait_for(started.wait(), timeout=2)
    stopping = asyncio.create_task(server.stop())
    try:
        await asyncio.wait_for(cancelling.wait(), timeout=2)
        body: dict[str, Any] = {
            "conversation_id": str(other["id"]),
            "message": {"text": "new"} if endpoint == "job" else "new",
            "stream": endpoint == "sse",
        }
        request = cast(web.Request, cast(Any, _DummyRequest(_json=body)))
        response: web.StreamResponse
        if endpoint == "job":
            response = await server._chat_job_create_handler(request)
        else:
            response = await server._chat_handler(request)
        assert response.status == 503
        assert len(manager._jobs) == 1
        assert calls == ["old"]
        release.set()
        await asyncio.wait_for(stopping, timeout=2)
        assert job.status == "cancelled"
        assert job.done.is_set()
        assert not await manager.has_running_job()
        with pytest.raises(runtime_api_chat.ChatJobManagerClosingError):
            await manager.create_job("after stop")
    finally:
        release.set()
        await stopping


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_creation", [False, True])
async def test_chat_stop_waits_for_in_progress_history_write(
    cancel_creation: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    started = threading.Event()
    release = threading.Event()
    server = RuntimeAPIServer(_context(), host="127.0.0.1", port=8788)
    manager = server._chat_job_manager
    await manager.conversation_store.ensure_ready()
    conversation = await manager.conversation_store.ensure_default_conversation()
    conversation_id = str(conversation["id"])
    history_path = manager.conversation_store._path_for(conversation_id)
    original_write = async_io.write_json_sync

    def controlled_write(
        file_path: Path | str, data: Any, use_lock: bool = True
    ) -> None:
        if Path(file_path) == history_path and data.get("messages"):
            started.set()
            if not release.wait(timeout=3):
                raise TimeoutError("history write not released")
        original_write(file_path, data, use_lock)

    async def run_chat(_ctx: Any, **_kwargs: Any) -> str:
        await asyncio.Event().wait()
        return "chat"

    monkeypatch.setattr(async_io, "write_json_sync", controlled_write)
    run_mock = AsyncMock(side_effect=run_chat)
    monkeypatch.setattr(runtime_api_chat, "run_webui_chat", run_mock)
    creation = asyncio.create_task(
        manager.create_job("hello", conversation_id, pre_record_user_history=True)
    )
    stopping: asyncio.Task[None] | None = None
    try:
        assert await asyncio.wait_for(asyncio.to_thread(started.wait, 1), timeout=2)
        stopping = asyncio.create_task(server.stop())
        await asyncio.sleep(0)
        assert manager._closing
        with pytest.raises(runtime_api_chat.ChatJobManagerClosingError):
            await manager.create_job("new")
        if cancel_creation:
            creation.cancel()
            await asyncio.sleep(0)
            assert not creation.done()
        assert not stopping.done()
        release.set()
        if cancel_creation:
            with pytest.raises(asyncio.CancelledError):
                await creation
            run_mock.assert_not_awaited()
            assert not manager._jobs
        else:
            job = await creation
            await asyncio.wait_for(stopping, timeout=2)
            assert job.status == "cancelled"
            assert job.done.is_set()
            assert job.task is not None and job.task.done()
        await asyncio.wait_for(stopping, timeout=2)
        assert not await manager.has_running_job()
        page = await manager.conversation_store.get_history_page(
            conversation_id, limit=50, before=None
        )
        assert [record["message"] for record in page.records] == ["hello"]
        assert (
            len(json.loads(history_path.read_text(encoding="utf-8"))["messages"]) == 1
        )
    finally:
        release.set()
        await asyncio.gather(creation, return_exceptions=True)
        if stopping is not None:
            await stopping


@pytest.mark.asyncio
async def test_runtime_api_stop_cancels_running_webchat_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def _fake_run_webui_chat(_ctx: Any, **_kwargs: Any) -> str:
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise
        return "chat"

    monkeypatch.setattr(runtime_api_chat, "run_webui_chat", _fake_run_webui_chat)
    server = RuntimeAPIServer(_context(), host="127.0.0.1", port=8788)
    job = await server._chat_job_manager.create_job("hello")
    await asyncio.wait_for(started.wait(), timeout=1)

    await server.stop()

    assert cancelled.is_set()
    assert job.status == "cancelled"
    assert job.done.is_set()
    assert job.history_finalized is True


@pytest.mark.asyncio
async def test_runtime_api_stop_recancels_shutdown_task_after_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(runtime_api_chat, "SHUTDOWN_TASK_TIMEOUT", 0.01)
    started = asyncio.Event()
    cancel_count = 0

    async def _resist_first_cancel() -> None:
        nonlocal cancel_count
        started.set()
        while True:
            try:
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                cancel_count += 1
                if cancel_count >= 2:
                    raise

    server = RuntimeAPIServer(_context(), host="127.0.0.1", port=8788)
    job = runtime_api_chat.ChatJob(
        job_id="job-resist-cancel",
        text="hello",
        created_at=0.0,
        updated_at=0.0,
        status="running",
    )
    job.task = asyncio.create_task(_resist_first_cancel())
    async with server._chat_job_manager._lock:
        server._chat_job_manager._jobs[job.job_id] = job
    await asyncio.wait_for(started.wait(), timeout=1)

    await asyncio.wait_for(server.stop(), timeout=1)

    assert cancel_count == 2
    assert job.status == "cancelled"
    assert job.done.is_set()


@pytest.mark.asyncio
async def test_chat_job_events_refreshes_stage_without_advancing_seq(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = asyncio.Event()

    async def _fake_run_webui_chat(_ctx: Any, **_kwargs: Any) -> str:
        await release.wait()
        return "chat"

    context = _context()
    monkeypatch.setattr(web, "StreamResponse", _DummyStreamResponse)
    monkeypatch.setattr(runtime_api_chat, "run_webui_chat", _fake_run_webui_chat)
    server = RuntimeAPIServer(context, host="127.0.0.1", port=8788)
    job = await server._chat_job_manager.create_job("hello")
    await asyncio.sleep(0.01)
    request = cast(
        web.Request,
        cast(
            Any,
            _DummyRequest(
                match_info={"job_id": job.job_id},
                query={"after": str(job.next_seq - 1)},
                headers={"Accept": "text/event-stream"},
                transport=_DummyTransport(closing_after_writes=1),
            ),
        ),
    )

    response = await server._chat_job_events_handler(request)
    events = _decode_sse(cast(_DummyStreamResponse, response).writes)

    assert events[0]["event"] == "stage"
    assert events[0]["seq"] == job.next_seq - 1
    assert events[0]["payload"]["stage"] == job.current_stage
    assert isinstance(events[0]["payload"]["elapsed_ms"], int)
    release.set()
    await server._chat_job_manager.cancel_job(job.job_id)


@pytest.mark.asyncio
async def test_chat_job_events_refreshes_agent_stage_without_advancing_seq(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = asyncio.Event()

    async def _fake_run_webui_chat(
        _ctx: Any,
        *,
        webchat_event_callback: Any = None,
        **_kwargs: Any,
    ) -> str:
        assert webchat_event_callback is not None
        await webchat_event_callback(
            "tool_start",
            {
                "tool_call_id": "call_agent",
                "webchat_call_id": "call_agent",
                "name": "web_agent",
                "api_name": "web_agent",
                "arguments": {"prompt": "search"},
                "is_agent": True,
            },
        )
        await webchat_event_callback(
            "agent_stage",
            {
                "webchat_call_id": "call_agent",
                "agent_name": "web_agent",
                "stage": "waiting_model",
                "detail": "iteration=1",
            },
        )
        await release.wait()
        await webchat_event_callback(
            "tool_end",
            {
                "tool_call_id": "call_agent",
                "webchat_call_id": "call_agent",
                "name": "web_agent",
                "api_name": "web_agent",
                "ok": True,
                "result": "ok",
                "is_agent": True,
            },
        )
        return "chat"

    monkeypatch.setattr(web, "StreamResponse", _DummyStreamResponse)
    monkeypatch.setattr(runtime_api_chat, "run_webui_chat", _fake_run_webui_chat)
    server = RuntimeAPIServer(_context(), host="127.0.0.1", port=8788)
    job = await server._chat_job_manager.create_job("hello")

    for _ in range(20):
        if any(event.event == "agent_stage" for event in job.events):
            break
        await asyncio.sleep(0.01)
    after = job.next_seq - 1
    request = cast(
        web.Request,
        cast(
            Any,
            _DummyRequest(
                match_info={"job_id": job.job_id},
                query={"after": str(after)},
                headers={"Accept": "text/event-stream"},
                transport=_DummyTransport(closing_after_writes=2),
            ),
        ),
    )

    response = await server._chat_job_events_handler(request)
    events = _decode_sse(cast(_DummyStreamResponse, response).writes)

    agent_stage_events = [event for event in events if event["event"] == "agent_stage"]
    assert agent_stage_events
    assert agent_stage_events[0]["seq"] == after
    assert agent_stage_events[0]["payload"]["webchat_call_id"] == "call_agent"
    assert agent_stage_events[0]["payload"]["stage"] == "waiting_model"
    assert isinstance(agent_stage_events[0]["payload"]["stage_elapsed_ms"], int)
    release.set()
    await server._chat_job_manager.cancel_job(job.job_id)


@pytest.mark.asyncio
async def test_chat_job_events_json_returns_incremental_events_and_live_stage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = asyncio.Event()

    async def _fake_run_webui_chat(
        _ctx: Any,
        *,
        webchat_event_callback: Any = None,
        **_kwargs: Any,
    ) -> str:
        assert webchat_event_callback is not None
        await webchat_event_callback(
            "tool_start",
            {
                "tool_call_id": "call_agent",
                "webchat_call_id": "call_agent",
                "name": "web_agent",
                "api_name": "web_agent",
                "arguments": {"prompt": "search"},
                "is_agent": True,
            },
        )
        await webchat_event_callback(
            "agent_stage",
            {
                "webchat_call_id": "call_agent",
                "agent_name": "web_agent",
                "stage": "waiting_model",
            },
        )
        await release.wait()
        await webchat_event_callback(
            "tool_end",
            {
                "tool_call_id": "call_agent",
                "webchat_call_id": "call_agent",
                "name": "web_agent",
                "api_name": "web_agent",
                "ok": True,
                "result": "ok",
                "is_agent": True,
            },
        )
        return "chat"

    monkeypatch.setattr(runtime_api_chat, "run_webui_chat", _fake_run_webui_chat)
    server = RuntimeAPIServer(_context(), host="127.0.0.1", port=8788)
    job = await server._chat_job_manager.create_job("hello")

    for _ in range(20):
        if any(event.event == "agent_stage" for event in job.events):
            break
        await asyncio.sleep(0.01)
    after = job.next_seq - 1
    request = cast(
        web.Request,
        cast(
            Any,
            _DummyRequest(
                match_info={"job_id": job.job_id},
                query={"after": str(after), "format": "json"},
                headers={"Accept": "application/json"},
                transport=_DummyTransport(),
            ),
        ),
    )

    response = cast(web.Response, await server._chat_job_events_handler(request))
    payload = json.loads(response.text or "{}")

    assert payload["after"] == after
    assert payload["last_seq"] == after
    assert payload["job"]["current_agent_stages"][0]["stage"] == "waiting_model"
    assert payload["job"]["current_tool_calls"][0]["webchat_call_id"] == "call_agent"
    assert payload["job"]["current_tool_calls"][0]["status"] == "running"
    assert payload["job"]["current_tool_calls"][0]["is_agent"] is True
    assert isinstance(payload["job"]["current_tool_calls"][0]["duration_ms"], int)
    assert isinstance(payload["job"]["current_tool_calls"][0]["started_at"], float)
    assert payload["job"]["current_tool_calls"][0]["current_stage"] == "waiting_model"
    assert payload["events"][0]["event"] == "stage"
    assert payload["events"][1]["event"] == "agent_stage"
    assert payload["events"][1]["seq"] == after
    assert payload["events"][1]["payload"]["transient"] is True
    release.set()
    await server._chat_job_manager.cancel_job(job.job_id)


@pytest.mark.asyncio
async def test_chat_job_events_reject_wrong_conversation_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = asyncio.Event()

    async def _fake_run_webui_chat(_ctx: Any, **_kwargs: Any) -> str:
        await release.wait()
        return "chat"

    monkeypatch.setattr(runtime_api_chat, "run_webui_chat", _fake_run_webui_chat)
    server = RuntimeAPIServer(_context(), host="127.0.0.1", port=8788)
    conversation = (
        await server._chat_job_manager.conversation_store.create_conversation()
    )
    conversation_id = str(conversation["id"])
    job = await server._chat_job_manager.create_job("hello", conversation_id)

    request = cast(
        web.Request,
        cast(
            Any,
            _DummyRequest(
                match_info={"job_id": job.job_id},
                query={"after": "0", "format": "json", "conversation_id": "other"},
                headers={"Accept": "application/json"},
                transport=_DummyTransport(),
            ),
        ),
    )

    response = cast(web.Response, await server._chat_job_events_handler(request))
    payload = json.loads(response.text or "{}")

    assert response.status == 404
    assert payload["error"] == "Job not found"
    release.set()
    await server._chat_job_manager.cancel_job(job.job_id)


@pytest.mark.asyncio
async def test_chat_job_persists_webchat_lifecycle_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    history_calls: list[dict[str, Any]] = []

    class _History:
        async def add_private_message(self, **kwargs: Any) -> None:
            history_calls.append(dict(kwargs))

        async def flush_pending_saves(self) -> None:
            return None

    async def _fake_run_webui_chat(
        _ctx: Any,
        *,
        text: str,
        send_output: Any,
        webchat_event_callback: Any = None,
    ) -> str:
        assert text == "hello"
        assert webchat_event_callback is not None
        await webchat_event_callback("stage", {"stage": "waiting_model"})
        await webchat_event_callback("token_delta", {"delta": "ignored"})
        await webchat_event_callback(
            "tool_start",
            {
                "tool_call_id": "call_1",
                "webchat_call_id": "agent_1",
                "name": "web_agent",
                "api_name": "web_agent",
                "arguments": {"prompt": "search"},
                "is_agent": True,
            },
        )
        await webchat_event_callback(
            "agent_stage",
            {
                "webchat_call_id": "agent_1",
                "name": "web_agent",
                "agent_name": "web_agent",
                "stage": "waiting_model",
                "detail": "iteration=1",
                "is_agent": True,
            },
        )
        await webchat_event_callback(
            "tool_start",
            {
                "tool_call_id": "call_1_1",
                "webchat_call_id": "agent_1/search_1",
                "parent_webchat_call_id": "agent_1",
                "name": "search",
                "api_name": "search",
                "arguments": {"q": "test"},
                "is_agent": False,
                "depth": 1,
                "agent_path": ["web_agent"],
            },
        )
        await webchat_event_callback(
            "tool_end",
            {
                "tool_call_id": "call_1_1",
                "webchat_call_id": "agent_1/search_1",
                "parent_webchat_call_id": "agent_1",
                "name": "search",
                "api_name": "search",
                "ok": True,
                "result": "nested result",
                "is_agent": False,
                "depth": 1,
                "agent_path": ["web_agent"],
            },
        )
        await send_output(42, "final")
        await webchat_event_callback(
            "tool_end",
            {
                "tool_call_id": "call_1",
                "webchat_call_id": "agent_1",
                "name": "web_agent",
                "api_name": "web_agent",
                "ok": True,
                "result": "agent result",
                "is_agent": True,
            },
        )
        return "chat"

    context = _context()
    context.history_manager = _History()
    monkeypatch.setattr(runtime_api_chat, "run_webui_chat", _fake_run_webui_chat)
    server = RuntimeAPIServer(context, host="127.0.0.1", port=8788)

    response = await server._chat_job_create_handler(
        cast(
            web.Request, cast(Any, _DummyRequest(_json={"message": "hello"}, query={}))
        )
    )
    job_id = str(json.loads(response.text or "{}")["job_id"])
    detail_request = cast(
        web.Request,
        cast(Any, _DummyRequest(match_info={"job_id": job_id}, query={})),
    )
    for _ in range(20):
        detail_response = await server._chat_job_detail_handler(detail_request)
        detail_payload = json.loads(detail_response.text or "{}")
        if detail_payload["history_finalized"] is True:
            break
        await asyncio.sleep(0.01)

    assert history_calls == []
    call = await _last_webchat_record(server)
    assert call["user_id"] == "42"
    assert call["message"] == "final"
    webchat = call["webchat"]
    assert webchat["display_only"] is True
    assert webchat["job_id"] == job_id
    assert isinstance(webchat["duration_ms"], int)
    assert webchat["finished_at"] is not None
    assert [event["event"] for event in webchat["events"]] == [
        "agent_start",
        "agent_stage",
        "tool_start",
        "tool_end",
        "message",
        "agent_end",
    ]
    assert webchat["events"][0]["payload"]["webchat_call_id"] == "agent_1"
    assert webchat["events"][1]["payload"]["stage"] == "waiting_model"
    assert webchat["events"][1]["payload"]["job_id"] == job_id
    assert isinstance(webchat["events"][1]["payload"]["stage_elapsed_ms"], int)
    assert webchat["events"][2]["payload"]["parent_webchat_call_id"] == "agent_1"
    assert webchat["events"][3]["payload"]["result_preview"] == "nested result"
    assert "duration_ms" in webchat["events"][3]["payload"]
    assert webchat["events"][4]["payload"]["content"] == "final"
    assert webchat["events"][4]["payload"]["parent_webchat_call_id"] == "agent_1"
    assert webchat["events"][5]["payload"]["result_preview"] == "agent result"
    assert len(webchat["calls"]) == 1
    assert webchat["calls"][0]["webchat_call_id"] == "agent_1"
    assert webchat["calls"][0]["is_agent"] is True
    assert webchat["calls"][0]["current_stage"] == "waiting_model"
    assert webchat["calls"][0]["children"][0]["webchat_call_id"] == "agent_1/search_1"
    assert webchat["calls"][0]["children"][0]["result_preview"] == "nested result"
    assert [item["type"] for item in webchat["timeline"]] == ["call"]
    assert webchat["timeline"][0]["call"]["webchat_call_id"] == "agent_1"
    assert webchat["timeline"][0]["call"]["children"][0]["name"] == "search"
    assert [item["type"] for item in webchat["calls"][0]["timeline"]] == [
        "stage",
        "call",
        "message",
    ]
    assert webchat["calls"][0]["timeline"][0]["stage"] == "waiting_model"
    assert webchat["calls"][0]["timeline"][1]["call"]["name"] == "search"
    assert webchat["calls"][0]["timeline"][2]["content"] == "final"


@pytest.mark.asyncio
async def test_chat_job_finalizes_unclosed_webchat_calls_as_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    history_calls: list[dict[str, Any]] = []

    class _History:
        async def add_private_message(self, **kwargs: Any) -> None:
            history_calls.append(dict(kwargs))

    async def _fake_run_webui_chat(
        _ctx: Any,
        *,
        text: str,
        send_output: Any,
        webchat_event_callback: Any = None,
    ) -> str:
        _ = send_output
        assert text == "hello"
        assert webchat_event_callback is not None
        await webchat_event_callback(
            "tool_start",
            {
                "tool_call_id": "call_1",
                "webchat_call_id": "call_1",
                "name": "search",
                "api_name": "search",
                "arguments": {"q": "test"},
                "is_agent": False,
            },
        )
        raise RuntimeError("boom")

    context = _context()
    context.history_manager = _History()
    monkeypatch.setattr(runtime_api_chat, "run_webui_chat", _fake_run_webui_chat)
    server = RuntimeAPIServer(context, host="127.0.0.1", port=8788)

    response = await server._chat_job_create_handler(
        cast(
            web.Request, cast(Any, _DummyRequest(_json={"message": "hello"}, query={}))
        )
    )
    job_id = str(json.loads(response.text or "{}")["job_id"])
    detail_request = cast(
        web.Request,
        cast(Any, _DummyRequest(match_info={"job_id": job_id}, query={})),
    )
    for _ in range(20):
        detail_response = await server._chat_job_detail_handler(detail_request)
        detail_payload = json.loads(detail_response.text or "{}")
        if detail_payload["history_finalized"] is True:
            break
        await asyncio.sleep(0.01)

    assert history_calls == []
    webchat = (await _last_webchat_record(server))["webchat"]
    assert [event["event"] for event in webchat["events"]] == [
        "tool_start",
        "tool_end",
    ]
    assert webchat["events"][1]["payload"]["ok"] is False
    assert webchat["events"][1]["payload"]["status"] == "error"
    assert webchat["calls"][0]["status"] == "error"
    assert webchat["timeline"][0]["call"]["status"] == "error"


@pytest.mark.asyncio
async def test_chat_job_history_persists_redacted_webchat_previews(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    history_calls: list[dict[str, Any]] = []

    class _History:
        async def add_private_message(self, **kwargs: Any) -> None:
            history_calls.append(dict(kwargs))

    async def _fake_run_webui_chat(
        _ctx: Any,
        *,
        text: str,
        send_output: Any,
        webchat_event_callback: Any = None,
    ) -> str:
        _ = text, send_output
        assert webchat_event_callback is not None
        await webchat_event_callback(
            "tool_start",
            {
                "tool_call_id": "call_secret",
                "webchat_call_id": "call_secret",
                "name": "external.search",
                "arguments": {
                    "q": "test",
                    "api_key": "sk-history-secret",
                    "headers": {"Authorization": "Bearer auth-history-secret"},
                },
            },
        )
        await webchat_event_callback(
            "tool_end",
            {
                "tool_call_id": "call_secret",
                "webchat_call_id": "call_secret",
                "name": "external.search",
                "ok": True,
                "result": {"password": "history-password", "summary": "ok"},
            },
        )
        return "chat"

    context = _context()
    context.history_manager = _History()
    monkeypatch.setattr(runtime_api_chat, "run_webui_chat", _fake_run_webui_chat)
    server = RuntimeAPIServer(context, host="127.0.0.1", port=8788)

    response = await server._chat_job_create_handler(
        cast(
            web.Request, cast(Any, _DummyRequest(_json={"message": "hello"}, query={}))
        )
    )
    job_id = str(json.loads(response.text or "{}")["job_id"])
    detail_request = cast(
        web.Request,
        cast(Any, _DummyRequest(match_info={"job_id": job_id}, query={})),
    )
    for _ in range(20):
        detail_response = await server._chat_job_detail_handler(detail_request)
        detail_payload = json.loads(detail_response.text or "{}")
        if detail_payload["history_finalized"] is True:
            break
        await asyncio.sleep(0.01)

    assert history_calls == []
    webchat = (await _last_webchat_record(server))["webchat"]
    dumped = json.dumps(webchat, ensure_ascii=False)
    assert "sk-history-secret" not in dumped
    assert "auth-history-secret" not in dumped
    assert "history-password" not in dumped
    assert "[redacted]" in dumped
    assert webchat["calls"][0]["result_preview"] == (
        '{"password":"[redacted]","summary":"ok"}'
    )
