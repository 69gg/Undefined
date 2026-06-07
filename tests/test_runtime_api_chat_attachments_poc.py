from __future__ import annotations

from collections.abc import Awaitable, Callable
import json
from types import SimpleNamespace
from typing import Any, cast

from aiohttp import FormData, web
from aiohttp.web_response import Response
from aiohttp.test_utils import TestClient, TestServer, make_mocked_request
import pytest

from Undefined.api import RuntimeAPIServer
from Undefined.api._context import RuntimeAPIContext
from Undefined.api.routes import chat


class _DummyConfig:
    def __init__(self, messages_send_url_file_max_size_mb: int | None = 7) -> None:
        self.messages_send_url_file_max_size_mb = messages_send_url_file_max_size_mb


def _ctx(*, max_size_mb: int | None = 7) -> RuntimeAPIContext:
    return RuntimeAPIContext(
        config_getter=lambda: _DummyConfig(max_size_mb),
        ai=SimpleNamespace(),
        onebot=SimpleNamespace(),
        scheduler=None,
        command_dispatcher=SimpleNamespace(),
        queue_manager=SimpleNamespace(),
        history_manager=None,
        naga_store=None,
    )


def _json(response: Response) -> Any:
    text = response.text
    assert text is not None
    return json.loads(text)


def _openapi_request() -> web.Request:
    return cast(
        web.Request,
        cast(
            Any,
            SimpleNamespace(
                query={},
                remote="127.0.0.1",
                scheme="http",
                host="127.0.0.1:8788",
            ),
        ),
    )


def _openapi_ctx() -> RuntimeAPIContext:
    return RuntimeAPIContext(
        config_getter=lambda: SimpleNamespace(
            api=SimpleNamespace(openapi_enabled=True),
        ),
        ai=SimpleNamespace(),
        onebot=SimpleNamespace(),
        scheduler=None,
        command_dispatcher=SimpleNamespace(),
        queue_manager=SimpleNamespace(),
        history_manager=None,
        naga_store=None,
    )


async def _post_upload(
    data: FormData,
    *,
    max_size_mb: int | None = 7,
) -> tuple[int, dict[str, Any]]:
    app = web.Application()
    ctx = _ctx(max_size_mb=max_size_mb)

    async def _handler(request: web.Request) -> web.Response:
        return await chat.chat_attachment_upload_handler(ctx, request)

    app.router.add_post("/api/v1/chat/attachments", _handler)
    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        response = await client.post("/api/v1/chat/attachments", data=data)
        payload = cast(dict[str, Any], await response.json())
        return response.status, payload
    finally:
        await client.close()


class _FailingReader:
    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    async def next(self) -> object:
        raise self._exc


class _FailingField:
    name = "file"
    filename = "broken.png"

    async def read_chunk(self, size: int = 8192) -> bytes:
        _ = size
        raise ValueError("bad chunk")


class _SingleFieldReader:
    def __init__(self, field: object) -> None:
        self._field = field
        self._used = False

    async def next(self) -> object | None:
        if self._used:
            return None
        self._used = True
        return self._field


class _MultipartRequest(SimpleNamespace):
    def __init__(self, multipart: Callable[[], Awaitable[object]]) -> None:
        super().__init__()
        self._multipart = multipart

    async def multipart(self) -> object:
        return await self._multipart()


@pytest.mark.asyncio
async def test_chat_attachment_capabilities_reports_runtime_limit() -> None:
    request = make_mocked_request("GET", "/api/v1/chat/attachments/capabilities")

    response = await chat.chat_attachment_capabilities_handler(_ctx(), request)

    assert response.status == 200
    payload_text = response.text
    assert payload_text is not None
    payload = json.loads(payload_text)
    assert payload["max_upload_size_bytes"] == 7340032
    assert payload["multipart_field"] == "file"


@pytest.mark.asyncio
async def test_chat_attachment_capabilities_clamps_explicit_zero_limit() -> None:
    request = make_mocked_request("GET", "/api/v1/chat/attachments/capabilities")

    response = await chat.chat_attachment_capabilities_handler(
        _ctx(max_size_mb=0), request
    )

    assert response.status == 200
    payload_text = response.text
    assert payload_text is not None
    payload = json.loads(payload_text)
    assert payload["max_upload_size_bytes"] == 1048576


@pytest.mark.asyncio
async def test_openapi_spec_includes_chat_attachment_poc_paths() -> None:
    server = RuntimeAPIServer(_openapi_ctx(), host="127.0.0.1", port=8788)

    response = await server._openapi_handler(_openapi_request())

    spec = _json(response)
    paths = spec["paths"]
    assert "/api/v1/chat/attachments/capabilities" in paths
    assert "get" in paths["/api/v1/chat/attachments/capabilities"]
    assert "/api/v1/chat/attachments" in paths
    assert "post" in paths["/api/v1/chat/attachments"]


@pytest.mark.asyncio
async def test_chat_attachment_upload_requires_multipart() -> None:
    request = make_mocked_request("POST", "/api/v1/chat/attachments")

    response = await chat.chat_attachment_upload_handler(_ctx(), request)

    assert response.status == 400
    assert response.text is not None
    assert "multipart" in response.text.lower()


@pytest.mark.asyncio
async def test_chat_attachment_upload_accepts_image_multipart() -> None:
    data = FormData()
    data.add_field(
        "file",
        b"\x89PNG\r\n\x1a\n",
        filename="photo.png",
        content_type="application/octet-stream",
    )

    status, payload = await _post_upload(data)

    assert status == 201
    attachment = payload["attachment"]
    assert attachment["size"] == 8
    assert attachment["media_type"] == "image/png"
    assert attachment["kind"] == "image"
    assert attachment["poc_discarded"] is True


@pytest.mark.asyncio
async def test_chat_attachment_upload_rejects_file_larger_than_limit() -> None:
    data = FormData()
    data.add_field(
        "file",
        b"x" * (1024 * 1024 + 1),
        filename="large.bin",
        content_type="application/octet-stream",
    )

    status, payload = await _post_upload(data, max_size_mb=1)

    assert status == 413
    assert payload["error"] == "file too large"
    assert payload["max_upload_size_bytes"] == 1048576


@pytest.mark.asyncio
async def test_chat_attachment_upload_requires_file_field_in_multipart() -> None:
    data = FormData()
    data.add_field(
        "note",
        b"hello",
        filename="note.txt",
        content_type="text/plain",
    )

    status, payload = await _post_upload(data)

    assert status == 400
    assert "file field" in str(payload["error"]).lower()


@pytest.mark.asyncio
async def test_chat_attachment_upload_accepts_file_after_other_parts() -> None:
    data = FormData()
    data.add_field("note", "metadata", content_type="text/plain")
    data.add_field(
        "file",
        b"abc",
        filename="avatar.jpg",
        content_type="application/octet-stream",
    )

    status, payload = await _post_upload(data)

    assert status == 201
    attachment = payload["attachment"]
    assert attachment["size"] == 3
    assert attachment["media_type"] == "image/jpeg"
    assert attachment["kind"] == "image"


@pytest.mark.asyncio
async def test_chat_attachment_upload_sanitizes_windows_path_and_control_chars() -> (
    None
):
    data = FormData()
    data.add_field(
        "file",
        b"abc",
        filename="C:\\fakepath\\bad\x01name.png",
        content_type="application/octet-stream",
    )

    status, payload = await _post_upload(data)

    assert status == 201
    attachment = payload["attachment"]
    assert attachment["name"] == "badname.png"
    assert attachment["media_type"] == "image/png"


@pytest.mark.asyncio
async def test_chat_attachment_upload_returns_400_when_reader_next_fails() -> None:
    async def _multipart() -> object:
        return _FailingReader(ValueError("bad boundary"))

    request = cast(web.Request, _MultipartRequest(_multipart))

    response = await chat.chat_attachment_upload_handler(_ctx(), request)

    assert response.status == 400
    assert response.text is not None
    assert "multipart" in response.text.lower()


@pytest.mark.asyncio
async def test_chat_attachment_upload_returns_400_when_read_chunk_fails() -> None:
    async def _multipart() -> object:
        return _SingleFieldReader(_FailingField())

    request = cast(web.Request, _MultipartRequest(_multipart))

    response = await chat.chat_attachment_upload_handler(_ctx(), request)

    assert response.status == 400
    assert response.text is not None
    assert "multipart" in response.text.lower()
