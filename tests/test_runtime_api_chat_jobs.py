from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from aiohttp import web

from Undefined.api import RuntimeAPIContext, RuntimeAPIServer
from Undefined.api.routes import chat as runtime_api_chat


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
        onebot=SimpleNamespace(connection_status=lambda: {}),
        ai=SimpleNamespace(
            attachment_registry=object(),
            memory_storage=SimpleNamespace(count=lambda: 0),
        ),
        command_dispatcher=SimpleNamespace(),
        queue_manager=SimpleNamespace(snapshot=lambda: {}),
        history_manager=SimpleNamespace(add_private_message=AsyncMock()),
    )


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
async def test_chat_job_events_after_reconnect_and_disconnect_does_not_cancel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = asyncio.Event()
    release = asyncio.Event()
    cancelled = False

    async def _fake_render_message_with_pic_placeholders(
        message: str,
        *,
        registry: Any,
        scope_key: str,
        strict: bool,
    ) -> Any:
        _ = registry, scope_key, strict
        return SimpleNamespace(
            delivery_text=f"rendered {message}",
            history_text=f"history {message}",
            attachments=[],
        )

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

    monkeypatch.setattr(
        runtime_api_chat,
        "render_message_with_pic_placeholders",
        _fake_render_message_with_pic_placeholders,
    )
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
                headers={},
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
                headers={},
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
    assert message_events[0]["payload"]["content"] == "rendered second"


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
                headers={},
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
async def test_chat_job_persists_webchat_lifecycle_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    history_calls: list[dict[str, Any]] = []

    class _History:
        async def add_private_message(self, **kwargs: Any) -> None:
            history_calls.append(dict(kwargs))

        async def flush_pending_saves(self) -> None:
            return None

    async def _fake_render_message_with_pic_placeholders(
        message: str,
        *,
        registry: Any,
        scope_key: str,
        strict: bool,
    ) -> Any:
        _ = registry, scope_key, strict
        return SimpleNamespace(
            delivery_text=f"rendered {message}",
            history_text=f"history {message}",
            attachments=[],
        )

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
    monkeypatch.setattr(
        runtime_api_chat,
        "render_message_with_pic_placeholders",
        _fake_render_message_with_pic_placeholders,
    )
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

    assert len(history_calls) == 1
    call = history_calls[0]
    assert call["user_id"] == 42
    assert call["text_content"] == "history final"
    webchat = call["webchat"]
    assert webchat["display_only"] is True
    assert webchat["job_id"] == job_id
    assert isinstance(webchat["duration_ms"], int)
    assert webchat["finished_at"] is not None
    assert [event["event"] for event in webchat["events"]] == [
        "agent_start",
        "tool_start",
        "tool_end",
        "message",
        "agent_end",
    ]
    assert webchat["events"][0]["payload"]["webchat_call_id"] == "agent_1"
    assert webchat["events"][1]["payload"]["parent_webchat_call_id"] == "agent_1"
    assert webchat["events"][2]["payload"]["result_preview"] == "nested result"
    assert "duration_ms" in webchat["events"][2]["payload"]
    assert webchat["events"][3]["payload"]["content"] == "rendered final"
    assert webchat["events"][3]["payload"]["parent_webchat_call_id"] == "agent_1"
    assert webchat["events"][4]["payload"]["result_preview"] == "agent result"
    assert len(webchat["calls"]) == 1
    assert webchat["calls"][0]["webchat_call_id"] == "agent_1"
    assert webchat["calls"][0]["is_agent"] is True
    assert webchat["calls"][0]["children"][0]["webchat_call_id"] == "agent_1/search_1"
    assert webchat["calls"][0]["children"][0]["result_preview"] == "nested result"
    assert [item["type"] for item in webchat["timeline"]] == ["call"]
    assert webchat["timeline"][0]["call"]["webchat_call_id"] == "agent_1"
    assert webchat["timeline"][0]["call"]["children"][0]["name"] == "search"
    assert [item["type"] for item in webchat["calls"][0]["timeline"]] == [
        "call",
        "message",
    ]
    assert webchat["calls"][0]["timeline"][0]["call"]["name"] == "search"
    assert webchat["calls"][0]["timeline"][1]["content"] == "rendered final"


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

    assert len(history_calls) == 1
    webchat = history_calls[0]["webchat"]
    assert [event["event"] for event in webchat["events"]] == [
        "tool_start",
        "tool_end",
    ]
    assert webchat["events"][1]["payload"]["ok"] is False
    assert webchat["events"][1]["payload"]["status"] == "error"
    assert webchat["calls"][0]["status"] == "error"
    assert webchat["timeline"][0]["call"]["status"] == "error"
