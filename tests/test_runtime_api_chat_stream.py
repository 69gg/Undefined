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


@pytest.fixture(autouse=True)
def _isolate_webchat_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)


class _DummyTransport:
    def is_closing(self) -> bool:
        return False


class _DummyRequest(SimpleNamespace):
    async def json(self) -> dict[str, object]:
        return {"message": "hello", "stream": True}


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

    async def prepare(self, request: web.Request) -> _DummyStreamResponse:
        _ = request
        return self

    async def write(self, data: bytes) -> None:
        self.writes.append(data)

    async def write_eof(self) -> None:
        self.eof_written = True


def test_sanitize_webchat_event_payload_compacts_webchat_private_send_tool() -> None:
    payload = runtime_api_chat._sanitize_webchat_event_payload(
        "tool_start",
        {
            "tool_call_id": "call_1",
            "name": "messages.send_message",
            "api_name": "messages-_-send_message",
            "arguments": {
                "target_type": "private",
                "target_id": 42,
                "message": "这段正文会作为 message 事件展示",
            },
        },
    )

    assert payload["ui_hint"] == "webchat_private_send"
    assert payload["arguments_preview"] == ""

    payload = runtime_api_chat._sanitize_webchat_event_payload(
        "tool_end",
        {
            "tool_call_id": "call_1",
            "name": "messages.send_message",
            "api_name": "messages-_-send_message",
            "ok": True,
            "result": "消息已发送（message_id=123）",
        },
    )

    assert payload["result_preview"] == "消息已发送（message_id=123）"

    payload = runtime_api_chat._sanitize_webchat_event_payload(
        "tool_end",
        {
            "tool_call_id": "call_2",
            "name": "messages.send_private_message",
            "api_name": "messages-_-send_private_message",
            "ok": True,
            "result": "私聊消息已发送给用户 42（message_id=456）",
        },
    )

    assert payload["ui_hint"] == "webchat_private_send"
    assert payload["result_preview"] == "私聊消息已发送给用户 42（message_id=456）"

    payload = runtime_api_chat._sanitize_webchat_event_payload(
        "tool_start",
        {
            "tool_call_id": "call_2",
            "name": "messages.send_private_message",
            "api_name": "messages-_-send_private_message",
            "arguments": {
                "target_id": 42,
                "message": "私聊正文",
            },
        },
    )

    assert payload["ui_hint"] == "webchat_private_send"
    assert payload["arguments_preview"] == ""


def test_sanitize_webchat_event_payload_keeps_group_send_message_details() -> None:
    payload = runtime_api_chat._sanitize_webchat_event_payload(
        "tool_start",
        {
            "tool_call_id": "call_1",
            "name": "messages.send_message",
            "api_name": "messages-_-send_message",
            "arguments": {
                "target_type": "group",
                "target_id": 10001,
                "message": "群聊消息",
            },
        },
    )

    assert "ui_hint" not in payload
    assert "群聊消息" in payload["arguments_preview"]
    assert json.loads(payload["arguments_preview"]) == {
        "target_type": "group",
        "target_id": 10001,
        "message": "群聊消息",
    }


def test_sanitize_webchat_event_payload_compacts_successful_end_tool() -> None:
    payload = runtime_api_chat._sanitize_webchat_event_payload(
        "tool_end",
        {
            "tool_call_id": "call_end",
            "name": "end",
            "api_name": "end",
            "ok": True,
            "result": "对话已结束",
        },
    )

    assert payload["ui_hint"] == "webchat_end"
    assert payload["result_preview"] == "对话已结束"


def test_sanitize_webchat_event_payload_redacts_secret_previews() -> None:
    payload = runtime_api_chat._sanitize_webchat_event_payload(
        "tool_start",
        {
            "tool_call_id": "call_secret",
            "name": "external.search",
            "arguments": {
                "q": "weather",
                "api_key": "sk-live-secret",
                "headers": {
                    "Authorization": "Bearer token-secret",
                    "Cookie": "sid=session-secret",
                },
            },
        },
    )

    preview = payload["arguments_preview"]
    assert "weather" in preview
    assert "sk-live-secret" not in preview
    assert "token-secret" not in preview
    assert "session-secret" not in preview
    assert "[redacted]" in preview

    payload = runtime_api_chat._sanitize_webchat_event_payload(
        "tool_end",
        {
            "tool_call_id": "call_secret",
            "name": "external.search",
            "ok": True,
            "result": "Authorization: Bearer result-secret password=plain-secret",
        },
    )

    result_preview = payload["result_preview"]
    assert "result-secret" not in result_preview
    assert "plain-secret" not in result_preview
    assert "[redacted]" in result_preview


@pytest.mark.skip(
    reason="render_message_with_pic_placeholders function no longer exists"
)
@pytest.mark.asyncio
async def test_runtime_chat_stream_renders_each_message_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    render_calls: list[str] = []

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
        history_manager=SimpleNamespace(
            add_private_message=AsyncMock(),
            flush_pending_saves=AsyncMock(),
        ),
    )
    server = RuntimeAPIServer(context, host="127.0.0.1", port=8788)

    async def _fake_run_webui_chat(_ctx: Any, *, text: str, send_output: Any) -> str:
        assert text == "hello"
        await send_output(42, "bot reply with <pic>")
        return "chat"

    monkeypatch.setattr(web, "StreamResponse", _DummyStreamResponse)
    monkeypatch.setattr(runtime_api_chat, "run_webui_chat", _fake_run_webui_chat)

    request = cast(
        web.Request,
        cast(
            Any,
            _DummyRequest(
                transport=_DummyTransport(),
            ),
        ),
    )

    response = await server._chat_handler(request)

    assert isinstance(response, _DummyStreamResponse)
    assert render_calls == ["bot reply with <pic>"]
    payload = b"".join(response.writes).decode("utf-8")
    assert payload.count("event: message") == 1
    assert "rendered stream reply" in payload
    assert "event: done" in payload
    assert response.eof_written is True
    context.history_manager.add_private_message.assert_not_awaited()
    conversation = await server._chat_job_manager.conversation_store.get_conversation(
        "legacy-system-42"
    )
    assert conversation is not None
    messages = conversation.get("messages")
    assert isinstance(messages, list)
    assert [item["message"] for item in messages] == ["rendered history reply"]


@pytest.mark.asyncio
async def test_runtime_chat_stream_uses_webchat_lifecycle_events_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
        history_manager=SimpleNamespace(
            add_private_message=AsyncMock(),
            flush_pending_saves=AsyncMock(),
        ),
    )
    server = RuntimeAPIServer(context, host="127.0.0.1", port=8788)

    async def _fake_run_webui_chat(
        _ctx: Any,
        *,
        text: str,
        send_output: Any,
        webchat_event_callback: Any = None,
    ) -> str:
        assert text == "hello"
        assert webchat_event_callback is not None
        await webchat_event_callback("token_delta", {"delta": "ignored"})
        await webchat_event_callback(
            "tool_delta",
            {"id": "call_1", "arguments_delta": '{"q"'},
        )
        await webchat_event_callback(
            "tool_start",
            {
                "tool_call_id": "call_1",
                "name": "search",
                "api_name": "search",
                "arguments": {"q": "weather"},
                "is_agent": False,
            },
        )
        await webchat_event_callback(
            "tool_end",
            {
                "tool_call_id": "call_1",
                "name": "search",
                "api_name": "search",
                "ok": True,
                "result": "sunny",
                "is_agent": False,
            },
        )
        await send_output(42, "final")
        return "chat"

    monkeypatch.setattr(web, "StreamResponse", _DummyStreamResponse)
    monkeypatch.setattr(runtime_api_chat, "run_webui_chat", _fake_run_webui_chat)

    request = cast(
        web.Request,
        cast(
            Any,
            _DummyRequest(
                transport=_DummyTransport(),
            ),
        ),
    )

    response = await server._chat_handler(request)

    assert isinstance(response, _DummyStreamResponse)
    payload = b"".join(response.writes).decode("utf-8")
    assert "event: token_delta" not in payload
    assert "event: tool_delta" not in payload
    assert "event: stage" in payload
    assert '"stage": "received"' in payload
    assert '"elapsed_ms":' in payload
    assert '"duration_ms":' in payload
    assert "event: tool_start" in payload
    assert "event: tool_end" in payload
    assert "event: message" in payload


@pytest.mark.asyncio
async def test_run_webui_chat_avoids_extra_blank_line_without_attachments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_prompt: dict[str, str] = {}
    captured_extra_context: dict[str, Any] = {}

    async def _fake_register_message_attachments(**kwargs: Any) -> Any:
        _ = kwargs
        return SimpleNamespace(normalized_text="hello", attachments=[])

    async def _fake_ask(full_question: str, **kwargs: Any) -> str:
        captured_extra_context.update(dict(kwargs.get("extra_context") or {}))
        captured_prompt["full_question"] = full_question
        return ""

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
            get_image=AsyncMock(),
            get_forward_msg=AsyncMock(),
        ),
        ai=SimpleNamespace(
            attachment_registry=object(),
            ask=_fake_ask,
            memory_storage=SimpleNamespace(count=lambda: 0),
            runtime_config=SimpleNamespace(),
        ),
        command_dispatcher=SimpleNamespace(
            parse_command=lambda _text: None,
            dispatch_private=AsyncMock(),
        ),
        queue_manager=SimpleNamespace(snapshot=lambda: {}),
        history_manager=SimpleNamespace(add_private_message=AsyncMock()),
    )
    server = RuntimeAPIServer(context, host="127.0.0.1", port=8788)

    monkeypatch.setattr(
        runtime_api_chat,
        "register_message_attachments",
        _fake_register_message_attachments,
    )
    monkeypatch.setattr(runtime_api_chat, "collect_context_resources", lambda _vars: {})

    sent_messages: list[tuple[int, str]] = []

    async def _send_output(user_id: int, message: str) -> None:
        sent_messages.append((user_id, message))

    result = await server._run_webui_chat(text="hello", send_output=_send_output)

    assert result == "chat"
    assert sent_messages == []
    assert "</content>\n\n </message>" not in captured_prompt["full_question"]
    assert captured_extra_context["webui_session"] is True
