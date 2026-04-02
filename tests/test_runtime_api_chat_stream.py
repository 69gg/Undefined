from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from aiohttp import web

from Undefined.api import RuntimeAPIContext, RuntimeAPIServer
from Undefined.api import app as runtime_api_app


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

    async def _fake_run_webui_chat(*, text: str, send_output: Any) -> str:
        assert text == "hello"
        await send_output(42, "bot reply with <pic>")
        return "chat"

    monkeypatch.setattr(
        runtime_api_app,
        "render_message_with_pic_placeholders",
        _fake_render_message_with_pic_placeholders,
    )
    monkeypatch.setattr(web, "StreamResponse", _DummyStreamResponse)
    monkeypatch.setattr(server, "_run_webui_chat", _fake_run_webui_chat)

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
