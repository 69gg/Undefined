from __future__ import annotations

import json
from types import SimpleNamespace

from aiohttp.test_utils import make_mocked_request
import pytest

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
async def test_chat_attachment_upload_requires_multipart() -> None:
    request = make_mocked_request("POST", "/api/v1/chat/attachments")

    response = await chat.chat_attachment_upload_handler(_ctx(), request)

    assert response.status == 400
    assert response.text is not None
    assert "multipart" in response.text.lower()
