from __future__ import annotations

from types import SimpleNamespace

from aiohttp.test_utils import make_mocked_request
import pytest

from Undefined.api._context import RuntimeAPIContext
from Undefined.api.routes import chat


class _DummyConfig:
    messages_send_url_file_max_size_mb: int = 7


def _ctx() -> RuntimeAPIContext:
    return RuntimeAPIContext(
        config_getter=lambda: _DummyConfig(),
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
    payload = response.text
    assert payload is not None
    assert '"max_upload_size_bytes": 7340032' in payload
    assert '"multipart_field": "file"' in payload


@pytest.mark.asyncio
async def test_chat_attachment_upload_requires_multipart() -> None:
    request = make_mocked_request("POST", "/api/v1/chat/attachments")

    response = await chat.chat_attachment_upload_handler(_ctx(), request)

    assert response.status == 400
    assert response.text is not None
    assert "multipart" in response.text.lower()
