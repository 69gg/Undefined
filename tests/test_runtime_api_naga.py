from __future__ import annotations

import asyncio
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
    security: Any | None = None,
) -> RuntimeAPIServer:
    security_impl = (
        security
        if security is not None
        else (
            _FakeSecurity(security_result)
            if security_result is not None
            else SimpleNamespace()
        )
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
            moderation_enabled=True,
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
        command_dispatcher=SimpleNamespace(security=security_impl),
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
async def test_naga_bind_callback_reject_is_idempotent(tmp_path: Path) -> None:
    store = NagaStore(tmp_path / "naga_bindings.json")
    await store.submit_binding("alice", qq_id=123, group_id=456, bind_uuid="uuid_a")
    sender = _FakeSender()
    server = _make_server(store=store, sender=sender)
    request = _make_request(
        json_body={
            "bind_uuid": "uuid_a",
            "naga_id": "alice",
            "status": "rejected",
            "reason": "duplicate",
        },
        headers={"Authorization": "Bearer shared-key"},
    )

    first = await server._naga_bind_callback_handler(request)
    second = await server._naga_bind_callback_handler(request)

    assert first.status == 200
    payload = _json(second)
    assert second.status == 200
    assert payload["idempotent"] is True


@pytest.mark.asyncio
async def test_naga_bind_callback_reject_returns_409_after_approval(
    tmp_path: Path,
) -> None:
    store = NagaStore(tmp_path / "naga_bindings.json")
    await store.submit_binding("alice", qq_id=123, group_id=456, bind_uuid="uuid_a")
    await store.activate_binding(
        bind_uuid="uuid_a",
        naga_id="alice",
        delivery_signature="sig_1",
    )
    sender = _FakeSender()
    server = _make_server(store=store, sender=sender)

    response = await server._naga_bind_callback_handler(
        _make_request(
            json_body={
                "bind_uuid": "uuid_a",
                "naga_id": "alice",
                "status": "rejected",
                "reason": "late reject",
            },
            headers={"Authorization": "Bearer shared-key"},
        )
    )

    payload = _json(response)
    assert response.status == 409
    assert "already approved" in payload["error"]


@pytest.mark.asyncio
async def test_naga_bind_callback_approved_returns_404_when_pending_missing(
    tmp_path: Path,
) -> None:
    store = NagaStore(tmp_path / "naga_bindings.json")
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
    assert response.status == 404
    assert "未处于待绑定状态" in payload["error"]


@pytest.mark.asyncio
async def test_naga_bind_callback_approved_returns_403_on_signature_mismatch(
    tmp_path: Path,
) -> None:
    store = NagaStore(tmp_path / "naga_bindings.json")
    await store.submit_binding("alice", qq_id=123, group_id=456, bind_uuid="uuid_a")
    await store.activate_binding(
        bind_uuid="uuid_a",
        naga_id="alice",
        delivery_signature="sig_1",
    )
    sender = _FakeSender()
    server = _make_server(store=store, sender=sender)

    response = await server._naga_bind_callback_handler(
        _make_request(
            json_body={
                "bind_uuid": "uuid_a",
                "naga_id": "alice",
                "status": "approved",
                "delivery_signature": "sig_wrong",
            },
            headers={"Authorization": "Bearer shared-key"},
        )
    )

    payload = _json(response)
    assert response.status == 403
    assert "delivery_signature 不匹配" in payload["error"]


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
    assert store._active_deliveries == {}


@pytest.mark.asyncio
async def test_naga_messages_send_requires_explicit_target_mode(tmp_path: Path) -> None:
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
                "target": {"qq_id": 123, "group_id": 456},
                "message": {"format": "text", "content": "hello"},
            },
            headers={"Authorization": "Bearer shared-key"},
        )
    )

    payload = _json(response)
    assert response.status == 400
    assert "target.mode must be" in payload["error"]
    assert sender.private_messages == []
    assert sender.group_messages == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mode", "expected_private", "expected_group"),
    [
        ("private", [(123, "hello")], []),
        ("group", [], [(456, "hello")]),
        ("both", [(123, "hello")], [(456, "hello")]),
    ],
)
async def test_naga_messages_send_routes_only_requested_target(
    tmp_path: Path,
    mode: str,
    expected_private: list[tuple[int, str]],
    expected_group: list[tuple[int, str]],
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
                "target": {"qq_id": 123, "group_id": 456, "mode": mode},
                "message": {"format": "text", "content": "hello"},
            },
            headers={"Authorization": "Bearer shared-key"},
        )
    )

    payload = _json(response)
    assert response.status == 200
    assert payload["ok"] is True
    assert payload["sent_private"] is bool(expected_private)
    assert payload["sent_group"] is bool(expected_group)
    assert sender.private_messages == expected_private
    assert sender.group_messages == expected_group
    assert store._active_deliveries == {}


@pytest.mark.asyncio
async def test_naga_messages_send_releases_delivery_when_group_not_allowed(
    tmp_path: Path,
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
            status="passed",
            categories=[],
            message="ok",
            model_name="naga-moderation",
        ),
    )
    server._ctx.config_getter().naga.allowed_groups = set()

    response = await server._naga_messages_send_handler(
        _make_request(
            json_body={
                "bind_uuid": "uuid_a",
                "naga_id": "alice",
                "delivery_signature": "sig_1",
                "target": {"qq_id": 123, "group_id": 456, "mode": "group"},
                "message": {"format": "text", "content": "hello"},
            },
            headers={"Authorization": "Bearer shared-key"},
        )
    )

    assert response.status == 403
    assert store._active_deliveries == {}


@pytest.mark.asyncio
async def test_naga_messages_send_both_mode_allows_private_when_group_not_allowed(
    tmp_path: Path,
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
            status="passed",
            categories=[],
            message="ok",
            model_name="naga-moderation",
        ),
    )
    server._ctx.config_getter().naga.allowed_groups = set()

    response = await server._naga_messages_send_handler(
        _make_request(
            json_body={
                "bind_uuid": "uuid_a",
                "naga_id": "alice",
                "delivery_signature": "sig_1",
                "target": {"qq_id": 123, "group_id": 456, "mode": "both"},
                "message": {"format": "text", "content": "hello"},
            },
            headers={"Authorization": "Bearer shared-key"},
        )
    )

    payload = _json(response)
    assert response.status == 200
    assert payload["ok"] is True
    assert payload["sent_private"] is True
    assert payload["sent_group"] is False
    assert payload["partial_success"] is True
    assert payload["delivery_status"] == "partial_success"
    assert sender.private_messages == [(123, "hello")]
    assert sender.group_messages == []
    assert store._active_deliveries == {}


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
async def test_naga_messages_send_skips_moderation_when_disabled(
    tmp_path: Path,
) -> None:
    class _ShouldNotRunSecurity:
        async def moderate_naga_message(
            self, *, message_format: str, content: str
        ) -> NagaModerationResult:
            del message_format, content
            raise AssertionError("moderation should be skipped")

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
        security=_ShouldNotRunSecurity(),
    )
    server._ctx.config_getter().naga.moderation_enabled = False

    response = await server._naga_messages_send_handler(
        _make_request(
            json_body={
                "bind_uuid": "uuid_a",
                "naga_id": "alice",
                "delivery_signature": "sig_1",
                "target": {"qq_id": 123, "group_id": 456, "mode": "group"},
                "message": {"format": "text", "content": "hello"},
            },
            headers={"Authorization": "Bearer shared-key"},
        )
    )

    payload = _json(response)
    assert response.status == 200
    assert payload["ok"] is True
    assert payload["moderation"]["status"] == "skipped_disabled"
    assert payload["sent_group"] is True
    assert sender.group_messages == [(456, "hello")]


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
        "Undefined.api.routes.naga.render_markdown_to_html", _render_markdown_to_html
    )
    monkeypatch.setattr(
        "Undefined.api.routes.naga.render_html_to_image", _render_html_to_image
    )

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
    assert payload["partial_success"] is False
    assert payload["delivery_status"] == "full_success"
    assert payload["moderation"]["status"] == "error_allowed"
    assert sender.private_messages
    assert sender.group_messages


@pytest.mark.asyncio
async def test_naga_messages_send_falls_back_when_markdown_conversion_fails(
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
        raise RuntimeError("markdown failed")

    monkeypatch.setattr(
        "Undefined.api.routes.naga.render_markdown_to_html", _render_markdown_to_html
    )

    response = await server._naga_messages_send_handler(
        _make_request(
            json_body={
                "bind_uuid": "uuid_a",
                "naga_id": "alice",
                "delivery_signature": "sig_1",
                "target": {"qq_id": 123, "group_id": 456, "mode": "private"},
                "message": {"format": "markdown", "content": "# hello"},
            },
            headers={"Authorization": "Bearer shared-key"},
        )
    )

    payload = _json(response)
    assert response.status == 200
    assert payload["ok"] is True
    assert payload["render_fallback"] is True
    assert payload["partial_success"] is False
    assert payload["delivery_status"] == "full_success"
    assert sender.private_messages == [(123, "# hello")]


@pytest.mark.asyncio
async def test_naga_messages_send_both_mode_reports_partial_success(
    tmp_path: Path,
) -> None:
    class _PartiallyFailingSender(_FakeSender):
        async def send_group_message(
            self, group_id: int, message: str, **_: Any
        ) -> None:
            del group_id, message
            raise RuntimeError("group failed")

    store = NagaStore(tmp_path / "naga_bindings.json")
    await store.submit_binding("alice", qq_id=123, group_id=456, bind_uuid="uuid_a")
    await store.activate_binding(
        bind_uuid="uuid_a",
        naga_id="alice",
        delivery_signature="sig_1",
    )
    sender = _PartiallyFailingSender()
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
                "target": {"qq_id": 123, "group_id": 456, "mode": "both"},
                "message": {"format": "text", "content": "hello"},
            },
            headers={"Authorization": "Bearer shared-key"},
        )
    )

    payload = _json(response)
    assert response.status == 200
    assert payload["ok"] is True
    assert payload["sent_private"] is True
    assert payload["sent_group"] is False
    assert payload["partial_success"] is True
    assert payload["delivery_status"] == "partial_success"
    assert sender.private_messages == [(123, "hello")]
    assert sender.group_messages == []


@pytest.mark.asyncio
async def test_naga_messages_send_deduplicates_completed_uuid(
    tmp_path: Path,
) -> None:
    class _CountingSecurity:
        def __init__(self) -> None:
            self.calls = 0

        async def moderate_naga_message(
            self, *, message_format: str, content: str
        ) -> NagaModerationResult:
            del message_format, content
            self.calls += 1
            return NagaModerationResult(
                blocked=False,
                status="passed",
                categories=[],
                message="ok",
                model_name="naga-moderation",
            )

    store = NagaStore(tmp_path / "naga_bindings.json")
    await store.submit_binding("alice", qq_id=123, group_id=456, bind_uuid="uuid_a")
    await store.activate_binding(
        bind_uuid="uuid_a",
        naga_id="alice",
        delivery_signature="sig_1",
    )
    sender = _FakeSender()
    security = _CountingSecurity()
    server = _make_server(store=store, sender=sender, security=security)
    body = {
        "bind_uuid": "uuid_a",
        "naga_id": "alice",
        "delivery_signature": "sig_1",
        "uuid": "req-1",
        "target": {"qq_id": 123, "group_id": 456, "mode": "group"},
        "message": {"format": "text", "content": "hello"},
    }

    first = await server._naga_messages_send_handler(
        _make_request(json_body=body, headers={"Authorization": "Bearer shared-key"})
    )
    second = await server._naga_messages_send_handler(
        _make_request(json_body=body, headers={"Authorization": "Bearer shared-key"})
    )

    first_payload = _json(first)
    second_payload = _json(second)
    assert first.status == 200
    assert second.status == 200
    assert first_payload == second_payload
    assert security.calls == 1
    assert sender.group_messages == [(456, "hello")]


@pytest.mark.asyncio
async def test_naga_messages_send_deduplicates_inflight_uuid(
    tmp_path: Path,
) -> None:
    class _BlockingSecurity:
        def __init__(self) -> None:
            self.calls = 0
            self.started = asyncio.Event()
            self.release = asyncio.Event()

        async def moderate_naga_message(
            self, *, message_format: str, content: str
        ) -> NagaModerationResult:
            del message_format, content
            self.calls += 1
            self.started.set()
            await self.release.wait()
            return NagaModerationResult(
                blocked=False,
                status="passed",
                categories=[],
                message="ok",
                model_name="naga-moderation",
            )

    store = NagaStore(tmp_path / "naga_bindings.json")
    await store.submit_binding("alice", qq_id=123, group_id=456, bind_uuid="uuid_a")
    await store.activate_binding(
        bind_uuid="uuid_a",
        naga_id="alice",
        delivery_signature="sig_1",
    )
    sender = _FakeSender()
    security = _BlockingSecurity()
    server = _make_server(store=store, sender=sender, security=security)
    body = {
        "bind_uuid": "uuid_a",
        "naga_id": "alice",
        "delivery_signature": "sig_1",
        "uuid": "req-2",
        "target": {"qq_id": 123, "group_id": 456, "mode": "group"},
        "message": {"format": "text", "content": "hello"},
    }

    first_task = asyncio.create_task(
        server._naga_messages_send_handler(
            _make_request(
                json_body=body, headers={"Authorization": "Bearer shared-key"}
            )
        )
    )
    await security.started.wait()
    second_task = asyncio.create_task(
        server._naga_messages_send_handler(
            _make_request(
                json_body=body, headers={"Authorization": "Bearer shared-key"}
            )
        )
    )
    await asyncio.sleep(0)
    security.release.set()

    first = await first_task
    second = await second_task

    assert _json(first) == _json(second)
    assert security.calls == 1
    assert sender.group_messages == [(456, "hello")]


@pytest.mark.asyncio
async def test_naga_messages_send_rejects_uuid_payload_conflict(
    tmp_path: Path,
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
            status="passed",
            categories=[],
            message="ok",
            model_name="naga-moderation",
        ),
    )

    first = await server._naga_messages_send_handler(
        _make_request(
            json_body={
                "bind_uuid": "uuid_a",
                "naga_id": "alice",
                "delivery_signature": "sig_1",
                "uuid": "req-3",
                "target": {"qq_id": 123, "group_id": 456, "mode": "group"},
                "message": {"format": "text", "content": "hello"},
            },
            headers={"Authorization": "Bearer shared-key"},
        )
    )
    second = await server._naga_messages_send_handler(
        _make_request(
            json_body={
                "bind_uuid": "uuid_a",
                "naga_id": "alice",
                "delivery_signature": "sig_1",
                "uuid": "req-3",
                "target": {"qq_id": 123, "group_id": 456, "mode": "group"},
                "message": {"format": "text", "content": "hello again"},
            },
            headers={"Authorization": "Bearer shared-key"},
        )
    )

    assert first.status == 200
    assert second.status == 409
    assert "uuid reused with different payload" in _json(second)["error"]
    assert sender.group_messages == [(456, "hello")]


@pytest.mark.asyncio
async def test_naga_messages_send_both_mode_returns_403_if_group_blocked_and_private_fails(
    tmp_path: Path,
) -> None:
    class _PrivateFailingSender(_FakeSender):
        async def send_private_message(
            self, user_id: int, message: str, **_: Any
        ) -> None:
            del user_id, message
            raise RuntimeError("private failed")

    store = NagaStore(tmp_path / "naga_bindings.json")
    await store.submit_binding("alice", qq_id=123, group_id=456, bind_uuid="uuid_a")
    await store.activate_binding(
        bind_uuid="uuid_a",
        naga_id="alice",
        delivery_signature="sig_1",
    )
    sender = _PrivateFailingSender()
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
    server._ctx.config_getter().naga.allowed_groups = set()

    response = await server._naga_messages_send_handler(
        _make_request(
            json_body={
                "bind_uuid": "uuid_a",
                "naga_id": "alice",
                "delivery_signature": "sig_1",
                "target": {"qq_id": 123, "group_id": 456, "mode": "both"},
                "message": {"format": "text", "content": "hello"},
            },
            headers={"Authorization": "Bearer shared-key"},
        )
    )

    payload = _json(response)
    assert response.status == 403
    assert payload["error"] == "bound group is not in naga.allowed_groups"
    assert payload["sent_private"] is False
    assert payload["sent_group"] is False


@pytest.mark.asyncio
async def test_naga_messages_send_aborts_when_revoked_mid_flight(
    tmp_path: Path,
) -> None:
    class _BlockingSecurity:
        def __init__(self) -> None:
            self.started = asyncio.Event()
            self.release = asyncio.Event()

        async def moderate_naga_message(
            self, *, message_format: str, content: str
        ) -> NagaModerationResult:
            _ = message_format, content
            self.started.set()
            await self.release.wait()
            return NagaModerationResult(
                blocked=False,
                status="passed",
                categories=[],
                message="ok",
                model_name="naga-moderation",
            )

    store = NagaStore(tmp_path / "naga_bindings.json")
    await store.submit_binding("alice", qq_id=123, group_id=456, bind_uuid="uuid_a")
    await store.activate_binding(
        bind_uuid="uuid_a",
        naga_id="alice",
        delivery_signature="sig_1",
    )
    sender = _FakeSender()
    security = _BlockingSecurity()
    server = _make_server(store=store, sender=sender, security=security)

    send_task = asyncio.create_task(
        server._naga_messages_send_handler(
            _make_request(
                json_body={
                    "bind_uuid": "uuid_a",
                    "naga_id": "alice",
                    "delivery_signature": "sig_1",
                    "target": {"qq_id": 123, "group_id": 456, "mode": "both"},
                    "message": {"format": "text", "content": "hello"},
                },
                headers={"Authorization": "Bearer shared-key"},
            )
        )
    )
    await security.started.wait()

    unbind_task = asyncio.create_task(
        server._naga_unbind_handler(
            _make_request(
                json_body={
                    "bind_uuid": "uuid_a",
                    "naga_id": "alice",
                    "delivery_signature": "sig_1",
                },
                headers={"Authorization": "Bearer shared-key"},
            )
        )
    )

    security.release.set()
    send_response = await send_task
    unbind_response = await unbind_task

    send_payload = _json(send_response)
    unbind_payload = _json(unbind_response)
    assert send_response.status == 409
    assert "吊销" in send_payload["error"]
    assert sender.private_messages == []
    assert sender.group_messages == []
    assert unbind_response.status == 200
    assert unbind_payload["idempotent"] is False


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


@pytest.mark.asyncio
async def test_naga_unbind_handler_old_generation_is_idempotent_after_rebind(
    tmp_path: Path,
) -> None:
    store = NagaStore(tmp_path / "naga_bindings.json")
    await store.submit_binding("alice", qq_id=123, group_id=456, bind_uuid="uuid_a")
    await store.activate_binding(
        bind_uuid="uuid_a",
        naga_id="alice",
        delivery_signature="sig_1",
    )
    sender = _FakeSender()
    server = _make_server(store=store, sender=sender)
    old_request = _make_request(
        json_body={
            "bind_uuid": "uuid_a",
            "naga_id": "alice",
            "delivery_signature": "sig_1",
        },
        headers={"Authorization": "Bearer shared-key"},
    )

    first = await server._naga_unbind_handler(old_request)
    assert first.status == 200

    await store.submit_binding("alice", qq_id=789, group_id=456, bind_uuid="uuid_b")
    await store.activate_binding(
        bind_uuid="uuid_b",
        naga_id="alice",
        delivery_signature="sig_2",
    )

    second = await server._naga_unbind_handler(old_request)

    payload = _json(second)
    current = store.get_binding("alice")
    assert second.status == 200
    assert payload["idempotent"] is True
    assert current is not None
    assert current.bind_uuid == "uuid_b"
    assert current.revoked is False


@pytest.mark.asyncio
async def test_openapi_only_exposes_enabled_naga_routes(tmp_path: Path) -> None:
    store = NagaStore(tmp_path / "naga_bindings.json")
    sender = _FakeSender()
    server = _make_server(store=store, sender=sender)

    response = await server._openapi_handler(_make_request())
    payload = _json(response)
    assert "/api/v1/naga/messages/send" in payload["paths"]
    assert payload["paths"]["/api/v1/naga/messages/send"]["post"]["security"] == [
        {"BearerAuth": []}
    ]

    cfg = server._ctx.config_getter()
    cfg.naga.enabled = False
    response_disabled = await server._openapi_handler(_make_request())
    payload_disabled = _json(response_disabled)
    assert "/api/v1/naga/messages/send" not in payload_disabled["paths"]
