from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from aiohttp import web

from Undefined.api import RuntimeAPIContext, RuntimeAPIServer
from Undefined.api.routes import chat as runtime_api_chat


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


@pytest.mark.asyncio
async def test_runtime_chat_stream_renders_each_message_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    render_calls: list[str] = []

    async def _fake_render_message_with_pic_placeholders(
        message: str,
        *,
        registry: Any,
        scope_key: str,
        strict: bool,
    ) -> Any:
        _ = registry, scope_key, strict
        render_calls.append(message)
        return SimpleNamespace(
            delivery_text="rendered stream reply",
            history_text="rendered history reply",
            attachments=[],
        )

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
        ai=SimpleNamespace(
            attachment_registry=object(),
            memory_storage=SimpleNamespace(count=lambda: 0),
        ),
        command_dispatcher=SimpleNamespace(),
        queue_manager=SimpleNamespace(snapshot=lambda: {}),
        history_manager=SimpleNamespace(add_private_message=AsyncMock()),
    )
    server = RuntimeAPIServer(context, host="127.0.0.1", port=8788)

    async def _fake_run_webui_chat(_ctx: Any, *, text: str, send_output: Any) -> str:
        assert text == "hello"
        await send_output(42, "bot reply with <pic>")
        return "chat"

    monkeypatch.setattr(
        runtime_api_chat,
        "render_message_with_pic_placeholders",
        _fake_render_message_with_pic_placeholders,
    )
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
