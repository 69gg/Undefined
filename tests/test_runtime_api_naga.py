from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from aiohttp import web
from aiohttp.web_response import Response

from Undefined.api import RuntimeAPIContext, RuntimeAPIServer
from Undefined.api.naga_store import NagaStore
from Undefined.services.security import NagaModerationResult


def _json(response: Response) -> Any:
    assert response.text is not None
    return json.loads(response.text)


class _FakeSender:
    def __init__(self) -> None:
        self.private_messages: list[tuple[int, str]] = []
        self.group_messages: list[tuple[int, str]] = []

    async def send_private_message(self, user_id: int, message: str, **_: Any) -> None:
        self.private_messages.append((user_id, message))

    async def send_group_message(self, group_id: int, message: str, **_: Any) -> None:
        self.group_messages.append((group_id, message))


class _FakeSecurity:
    def __init__(self, result: NagaModerationResult) -> None:
        self._result = result

    async def moderate_naga_message(
        self, *, message_format: str, content: str
    ) -> NagaModerationResult:
        _ = message_format, content
        return self._result


def _make_request(
    *,
    json_body: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> web.Request:
    ns = SimpleNamespace(
        query={},
        headers=headers or {},
        remote="127.0.0.1",
        scheme="http",
        host="127.0.0.1:8788",
    )
    if json_body is not None:

        async def _json_body() -> dict[str, Any]:
            return json_body

        ns.json = _json_body
    return cast(web.Request, cast(Any, ns))


def _make_server(
    *,
    store: NagaStore,
    sender: _FakeSender,
    security_result: NagaModerationResult | None = None,
) -> RuntimeAPIServer:
    security = (
        _FakeSecurity(security_result)
        if security_result is not None
        else SimpleNamespace()
    )
    cfg = SimpleNamespace(
        api=SimpleNamespace(
            enabled=True,
            host="127.0.0.1",
            port=8788,
            auth_key="testkey",
            openapi_enabled=True,
        ),
        nagaagent_mode_enabled=True,
        naga=SimpleNamespace(
            enabled=True,
            api_key="shared-key",
            allowed_groups={456},
        ),
        naga_model=SimpleNamespace(
            model_name="naga-moderation",
            api_url="https://api.example.com/v1",
            api_key="sk-naga",
        ),
    )
    context = RuntimeAPIContext(
        config_getter=lambda: cfg,
        onebot=SimpleNamespace(connection_status=lambda: {}),
        ai=SimpleNamespace(memory_storage=None),
        command_dispatcher=SimpleNamespace(security=security),
        queue_manager=SimpleNamespace(snapshot=lambda: {}),
        history_manager=SimpleNamespace(),
        sender=sender,
        naga_store=store,
    )
    return RuntimeAPIServer(context, host="127.0.0.1", port=8788)


@pytest.mark.asyncio
async def test_naga_bind_callback_activates_pending_binding(tmp_path: Path) -> None:
    store = NagaStore(tmp_path / "naga_bindings.json")
    await store.submit_binding("alice", qq_id=123, group_id=456, bind_uuid="uuid_a")
    sender = _FakeSender()
    server = _make_server(store=store, sender=sender)

    response = await server._naga_bind_callback_handler(
        _make_request(
            json_body={
                "bind_uuid": "uuid_a",
                "naga_id": "alice",
                "status": "approved",
                "delivery_signature": "sig_1",
            },
            headers={"Authorization": "Bearer shared-key"},
        )
    )

    payload = _json(response)
    assert response.status == 200
    assert payload["ok"] is True
    binding = store.get_binding("alice")
    assert binding is not None
    assert binding.delivery_signature == "sig_1"
    assert sender.private_messages


@pytest.mark.asyncio
async def test_naga_messages_send_rejects_target_mismatch(tmp_path: Path) -> None:
    store = NagaStore(tmp_path / "naga_bindings.json")
    await store.submit_binding("alice", qq_id=123, group_id=456, bind_uuid="uuid_a")
    await store.activate_binding(
        bind_uuid="uuid_a",
        naga_id="alice",
        delivery_signature="sig_1",
    )
    sender = _FakeSender()
    server = _make_server(
        store=store,
        sender=sender,
        security_result=NagaModerationResult(
            blocked=False,
            status="passed",
            categories=[],
            message="ok",
            model_name="naga-moderation",
        ),
    )

    response = await server._naga_messages_send_handler(
        _make_request(
            json_body={
                "bind_uuid": "uuid_a",
                "naga_id": "alice",
                "delivery_signature": "sig_1",
                "target": {"qq_id": 999, "group_id": 456, "mode": "private"},
                "message": {"format": "text", "content": "hello"},
            },
            headers={"Authorization": "Bearer shared-key"},
        )
    )

    assert response.status == 403
    payload = _json(response)
    assert "target does not match" in payload["error"]


@pytest.mark.asyncio
async def test_naga_messages_send_blocks_on_moderation_hit(tmp_path: Path) -> None:
    store = NagaStore(tmp_path / "naga_bindings.json")
    await store.submit_binding("alice", qq_id=123, group_id=456, bind_uuid="uuid_a")
    await store.activate_binding(
        bind_uuid="uuid_a",
        naga_id="alice",
        delivery_signature="sig_1",
    )
    sender = _FakeSender()
    server = _make_server(
        store=store,
        sender=sender,
        security_result=NagaModerationResult(
            blocked=True,
            status="blocked",
            categories=["personal_privacy"],
            message="contains privacy leak",
            model_name="naga-moderation",
        ),
    )

    response = await server._naga_messages_send_handler(
        _make_request(
            json_body={
                "bind_uuid": "uuid_a",
                "naga_id": "alice",
                "delivery_signature": "sig_1",
                "target": {"qq_id": 123, "group_id": 456, "mode": "private"},
                "message": {"format": "text", "content": "secret"},
            },
            headers={"Authorization": "Bearer shared-key"},
        )
    )

    assert response.status == 403
    payload = _json(response)
    assert payload["ok"] is False
    assert payload["moderation"]["status"] == "blocked"
    assert sender.private_messages == []


@pytest.mark.asyncio
async def test_naga_messages_send_allows_render_with_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = NagaStore(tmp_path / "naga_bindings.json")
    await store.submit_binding("alice", qq_id=123, group_id=456, bind_uuid="uuid_a")
    await store.activate_binding(
        bind_uuid="uuid_a",
        naga_id="alice",
        delivery_signature="sig_1",
    )
    sender = _FakeSender()
    server = _make_server(
        store=store,
        sender=sender,
        security_result=NagaModerationResult(
            blocked=False,
            status="error_allowed",
            categories=[],
            message="moderation timeout",
            model_name="naga-moderation",
        ),
    )

    async def _render_markdown_to_html(_: str) -> str:
        return "<p>hello</p>"

    async def _render_html_to_image(_: str, __: str) -> None:
        raise RuntimeError("render failed")

    monkeypatch.setattr(
        "Undefined.api.app.render_markdown_to_html", _render_markdown_to_html
    )
    monkeypatch.setattr("Undefined.api.app.render_html_to_image", _render_html_to_image)

    response = await server._naga_messages_send_handler(
        _make_request(
            json_body={
                "bind_uuid": "uuid_a",
                "naga_id": "alice",
                "delivery_signature": "sig_1",
                "target": {"qq_id": 123, "group_id": 456, "mode": "both"},
                "message": {"format": "markdown", "content": "# hello"},
            },
            headers={"Authorization": "Bearer shared-key"},
        )
    )

    payload = _json(response)
    assert response.status == 200
    assert payload["ok"] is True
    assert payload["render_fallback"] is True
    assert payload["moderation"]["status"] == "error_allowed"
    assert sender.private_messages
    assert sender.group_messages


@pytest.mark.asyncio
async def test_naga_unbind_handler_revokes_binding(tmp_path: Path) -> None:
    store = NagaStore(tmp_path / "naga_bindings.json")
    await store.submit_binding("alice", qq_id=123, group_id=456, bind_uuid="uuid_a")
    await store.activate_binding(
        bind_uuid="uuid_a",
        naga_id="alice",
        delivery_signature="sig_1",
    )
    sender = _FakeSender()
    server = _make_server(store=store, sender=sender)

    response = await server._naga_unbind_handler(
        _make_request(
            json_body={
                "bind_uuid": "uuid_a",
                "naga_id": "alice",
                "delivery_signature": "sig_1",
            },
            headers={"Authorization": "Bearer shared-key"},
        )
    )

    payload = _json(response)
    assert response.status == 200
    assert payload["ok"] is True
    binding = store.get_binding("alice")
    assert binding is not None
    assert binding.revoked is True
