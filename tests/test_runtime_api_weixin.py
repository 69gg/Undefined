from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any, cast

import pytest
from aiohttp import web
from unittest.mock import AsyncMock

from Undefined.api import RuntimeAPIContext, RuntimeAPIServer
from Undefined.weixin.service import WeixinConfirmationRequired


class _JsonRequest(SimpleNamespace):
    async def json(self) -> dict[str, Any]:
        return dict(self.body)


def _context(service: Any) -> RuntimeAPIContext:
    config = SimpleNamespace(
        api=SimpleNamespace(
            enabled=True,
            host="127.0.0.1",
            port=8788,
            auth_key="test-key",
            openapi_enabled=True,
        ),
        superadmin_qq=10001,
    )
    return RuntimeAPIContext(
        config_getter=lambda: config,
        onebot=SimpleNamespace(connection_status=lambda: {}),
        ai=SimpleNamespace(memory_storage=None),
        command_dispatcher=SimpleNamespace(),
        queue_manager=SimpleNamespace(snapshot=lambda: {}),
        history_manager=SimpleNamespace(),
        weixin_service=service,
    )


def _payload(response: web.Response) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(response.text or "{}"))


@pytest.mark.asyncio
async def test_weixin_status_never_requires_onebot_connection() -> None:
    service = SimpleNamespace(
        status=AsyncMock(
            return_value={"enabled": True, "running": True, "accounts": []}
        )
    )
    server = RuntimeAPIServer(_context(service), host="127.0.0.1", port=8788)

    response = await server._weixin_status_handler(
        cast(web.Request, cast(Any, SimpleNamespace()))
    )

    assert response.status == 200
    assert _payload(response)["running"] is True
    service.status.assert_awaited_once()


@pytest.mark.asyncio
async def test_privileged_login_returns_confirmation_challenge() -> None:
    service = SimpleNamespace(
        start_login=AsyncMock(
            side_effect=WeixinConfirmationRequired(
                "confirm-token", "管理员绑定警告", 123.0
            )
        )
    )
    server = RuntimeAPIServer(_context(service), host="127.0.0.1", port=8788)
    request = _JsonRequest(body={"alias": "primary", "qq_id": 10001})

    response = await server._weixin_login_start_handler(
        cast(web.Request, cast(Any, request))
    )
    payload = _payload(response)

    assert response.status == 409
    assert payload["requires_confirmation"] is True
    assert payload["confirmation_token"] == "confirm-token"


@pytest.mark.asyncio
async def test_login_response_does_not_expose_raw_qr_payload() -> None:
    result = SimpleNamespace(
        session_id="session-1",
        to_dict=lambda: {
            "session_id": "session-1",
            "qrcode_payload": "sensitive-qr-payload",
            "expires_at": 123.0,
        },
    )
    service = SimpleNamespace(start_login=AsyncMock(return_value=result))
    server = RuntimeAPIServer(_context(service), host="127.0.0.1", port=8788)
    request = _JsonRequest(body={"alias": "primary", "qq_id": 12345})

    response = await server._weixin_login_start_handler(
        cast(web.Request, cast(Any, request))
    )
    payload = _payload(response)

    assert response.status == 201
    assert "qrcode_payload" not in payload
    assert payload["qr_image_url"].endswith("/session-1/qr.png")


@pytest.mark.asyncio
async def test_qr_endpoint_returns_non_cached_png() -> None:
    service = SimpleNamespace(
        get_login_qrcode_payload=lambda _session_id: "https://qr.example.test/value"
    )
    server = RuntimeAPIServer(_context(service), host="127.0.0.1", port=8788)
    request = SimpleNamespace(match_info={"session_id": "session-1"})

    response = await server._weixin_login_qr_handler(
        cast(web.Request, cast(Any, request))
    )
    png_response = cast(web.Response, response)

    assert png_response.status == 200
    assert png_response.body is not None
    assert isinstance(png_response.body, bytes)
    assert png_response.body.startswith(b"\x89PNG\r\n\x1a\n")
    assert png_response.headers["Cache-Control"] == "no-store, max-age=0"
