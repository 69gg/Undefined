from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from aiohttp import web
from aiohttp.web_response import Response

from Undefined.api import RuntimeAPIContext, RuntimeAPIServer
from Undefined.api.naga_store import NagaStore
from Undefined.onebot.client import OneBotDeliveryUncertainError
from Undefined.services.security import NagaModerationResult
from Undefined.utils import io as async_io


@pytest.fixture(autouse=True)
def _isolate_runtime_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)


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
            mode="allowlist",
            allowed_group_ids=frozenset({456}),
            blocked_group_ids=frozenset(),
            allowed_private_ids=frozenset(),
            blocked_private_ids=frozenset(),
            is_group_allowed=lambda gid: int(gid) in {456},
            is_private_allowed=lambda uid, is_superadmin=False: True,
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
    naga = server._ctx.config_getter().naga
    naga.allowed_group_ids = frozenset()
    naga.is_group_allowed = lambda gid: False

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
async def test_naga_messages_send_both_mode_rejects_when_either_channel_denied(
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
    naga = server._ctx.config_getter().naga
    naga.allowed_group_ids = frozenset()
    naga.is_group_allowed = lambda gid: False

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
    assert payload["error"] == "naga policy denied"
    assert sender.private_messages == []
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
@pytest.mark.parametrize("mode", ["group", "both"])
async def test_naga_usage_write_failure_keeps_delivery_and_uuid_result(
    mode: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    class _Sender(_FakeSender):
        async def send_group_message(
            self, group_id: int, message: str, **kwargs: Any
        ) -> None:
            if mode == "both":
                raise RuntimeError("controlled group rejection")
            await super().send_group_message(group_id, message, **kwargs)

    path = tmp_path / "naga_bindings.json"
    store = NagaStore(path)
    await store.submit_binding("alice", qq_id=123, group_id=456, bind_uuid="uuid_a")
    await store.activate_binding(
        bind_uuid="uuid_a", naga_id="alice", delivery_signature="sig_1"
    )
    sender = _Sender()
    server = _make_server(store=store, sender=sender)
    started = threading.Event()
    release = threading.Event()
    original_write = async_io.write_json_sync
    statistics_writes = 0

    def write_usage(file_path: Path | str, data: Any, use_lock: bool = True) -> None:
        nonlocal statistics_writes
        if Path(file_path) == path:
            statistics_writes += 1
            started.set()
            if not release.wait(timeout=3):
                raise TimeoutError("usage write not released")
            raise OSError("usage disk unavailable")
        original_write(file_path, data, use_lock)

    monkeypatch.setattr(async_io, "write_json_sync", write_usage)
    body: dict[str, Any] = {
        "bind_uuid": "uuid_a",
        "naga_id": "alice",
        "delivery_signature": "sig_1",
        "uuid": "req-usage-failure",
        "target": {"qq_id": 123, "group_id": 456, "mode": mode},
        "message": {"format": "text", "content": "hello"},
    }

    async def send() -> Response:
        return await server._naga_messages_send_handler(
            _make_request(
                json_body=body, headers={"Authorization": "Bearer shared-key"}
            )
        )

    first = asyncio.create_task(send())
    second: asyncio.Task[Response] | None = None
    try:
        assert await asyncio.wait_for(asyncio.to_thread(started.wait, 1), timeout=2)
        assert len(sender.private_messages) + len(sender.group_messages) == 1
        second = asyncio.create_task(send())
        await asyncio.sleep(0)
        assert not first.done()
        release.set()
        first_response, second_response = await asyncio.wait_for(
            asyncio.gather(first, second), timeout=2
        )
        retry_response = await send()
        assert (
            first_response.status
            == second_response.status
            == retry_response.status
            == 200
        )
        payload = _json(first_response)
        assert payload == _json(second_response) == _json(retry_response)
        assert payload["ok"] is True
        assert payload["sent_private"] is (mode == "both")
        assert payload["sent_group"] is (mode == "group")
        assert payload["partial_success"] is (mode == "both")
        assert len(sender.private_messages) + len(sender.group_messages) == 1
        assert statistics_writes == 1
        assert not store._active_deliveries
        assert not server._naga_state.request_uuid_inflight
        assert "req-usage-failure" in server._naga_state.request_uuid_results
        assert "使用统计保存失败" in caplog.text
        assert (
            json.loads(path.read_text(encoding="utf-8"))["bindings"]["alice"][
                "use_count"
            ]
            == 0
        )
    finally:
        release.set()
        await asyncio.gather(
            first, *([second] if second is not None else []), return_exceptions=True
        )
        await server.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("statistics_fail", [False, True])
async def test_naga_cancel_after_delivery_commits_uuid_before_propagating(
    statistics_fail: bool,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "naga_bindings.json"
    store = NagaStore(path)
    await store.submit_binding("alice", qq_id=123, group_id=456, bind_uuid="uuid_a")
    await store.activate_binding(
        bind_uuid="uuid_a", naga_id="alice", delivery_signature="sig_1"
    )
    sender = _FakeSender()
    server = _make_server(store=store, sender=sender)
    started = threading.Event()
    release = threading.Event()
    original_write = async_io.write_json_sync
    writes = 0

    def write_usage(file_path: Path | str, data: Any, use_lock: bool = True) -> None:
        nonlocal writes
        if Path(file_path) == path:
            writes += 1
            started.set()
            if not release.wait(timeout=3):
                raise TimeoutError("usage write not released")
            if statistics_fail:
                raise OSError("usage disk unavailable")
        original_write(file_path, data, use_lock)

    monkeypatch.setattr(async_io, "write_json_sync", write_usage)
    body: dict[str, Any] = {
        "bind_uuid": "uuid_a",
        "naga_id": "alice",
        "delivery_signature": "sig_1",
        "uuid": "req-cancelled-usage",
        "target": {"qq_id": 123, "group_id": 456, "mode": "group"},
        "message": {"format": "text", "content": "hello"},
    }

    async def send() -> Response:
        return await server._naga_messages_send_handler(
            _make_request(
                json_body=body, headers={"Authorization": "Bearer shared-key"}
            )
        )

    owner = asyncio.create_task(send())
    try:
        assert await asyncio.wait_for(asyncio.to_thread(started.wait, 1), timeout=2)
        assert sender.group_messages == [(456, "hello")]
        assert "req-cancelled-usage" in server._naga_state.request_uuid_results
        assert not server._naga_state.request_uuid_inflight
        owner.cancel()
        await asyncio.sleep(0)
        owner.cancel()
        await asyncio.sleep(0)
        assert not owner.done()
        assert store._active_deliveries == {"uuid_a": 1}
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(owner, timeout=2)
        assert not store._active_deliveries
        assert not server._naga_state.send_inflight
        retry = await send()
        assert retry.status == 200
        assert _json(retry)["sent_group"] is True
        assert sender.group_messages == [(456, "hello")]
        assert writes == 1
        assert json.loads(path.read_text(encoding="utf-8"))["bindings"]["alice"][
            "use_count"
        ] == (0 if statistics_fail else 1)
    finally:
        release.set()
        await asyncio.gather(owner, return_exceptions=True)
        await server.stop()


@pytest.mark.asyncio
async def test_naga_uncertain_delivery_does_not_become_confirmed_success(
    tmp_path: Path,
) -> None:
    class _UncertainSender(_FakeSender):
        calls = 0

        async def send_group_message(
            self, group_id: int, message: str, **_kwargs: Any
        ) -> None:
            self.calls += 1
            raise OneBotDeliveryUncertainError(
                "send_group_msg", "controlled missing acknowledgement"
            )

    store = NagaStore(tmp_path / "naga_bindings.json")
    await store.submit_binding("alice", qq_id=123, group_id=456, bind_uuid="uuid_a")
    await store.activate_binding(
        bind_uuid="uuid_a", naga_id="alice", delivery_signature="sig_1"
    )
    sender = _UncertainSender()
    server = _make_server(store=store, sender=sender)
    body: dict[str, Any] = {
        "bind_uuid": "uuid_a",
        "naga_id": "alice",
        "delivery_signature": "sig_1",
        "uuid": "req-uncertain",
        "target": {"qq_id": 123, "group_id": 456, "mode": "group"},
        "message": {"format": "text", "content": "hello"},
    }
    request = _make_request(
        json_body=body, headers={"Authorization": "Bearer shared-key"}
    )
    first = await server._naga_messages_send_handler(request)
    retry = await server._naga_messages_send_handler(request)
    assert first.status == retry.status == 502
    assert _json(first) == _json(retry)
    assert _json(first)["ok"] is False
    assert _json(first)["sent_group"] is False
    assert sender.calls == 1
    assert not store._active_deliveries
    await server.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_cleanup", [False, True])
async def test_naga_failed_uuid_cleanup_survives_cancellation_and_waiters(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    cancel_cleanup: bool,
) -> None:
    entered = asyncio.Event()
    release_moderation = asyncio.Event()
    cleanup_started = asyncio.Event()

    class _Security:
        calls = 0

        async def moderate_naga_message(
            self, *, message_format: str, content: str
        ) -> NagaModerationResult:
            self.calls += 1
            if self.calls == 1:
                entered.set()
                await release_moderation.wait()
                raise RuntimeError("moderation failed before delivery")
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
        bind_uuid="uuid_a", naga_id="alice", delivery_signature="sig_1"
    )
    sender = _FakeSender()
    security = _Security()
    server = _make_server(store=store, sender=sender, security=security)
    state = server._naga_state
    fail_request_uuid = state.fail_request_uuid
    cleanup_calls = 0

    async def tracked_failure(
        request_uuid: str, payload_hash: str, exc: BaseException
    ) -> None:
        nonlocal cleanup_calls
        cleanup_calls += 1
        cleanup_started.set()
        await fail_request_uuid(request_uuid, payload_hash, exc)

    monkeypatch.setattr(state, "fail_request_uuid", tracked_failure)
    body: dict[str, Any] = {
        "bind_uuid": "uuid_a",
        "naga_id": "alice",
        "delivery_signature": "sig_1",
        "uuid": "req-failed-cleanup",
        "target": {"qq_id": 123, "group_id": 456, "mode": "group"},
        "message": {"format": "text", "content": "hello"},
    }

    async def send() -> Response:
        return await server._naga_messages_send_handler(
            _make_request(
                json_body=body, headers={"Authorization": "Bearer shared-key"}
            )
        )

    owner = asyncio.create_task(send())
    waiter: asyncio.Task[Response] | None = None
    lock_held = False
    try:
        await asyncio.wait_for(entered.wait(), 1)
        waiter = asyncio.create_task(send())
        await asyncio.sleep(0)
        assert sum(state.send_inflight.values()) == 2
        await state.request_uuid_lock.acquire()
        lock_held = True
        release_moderation.set()
        await asyncio.wait_for(cleanup_started.wait(), 1)
        if cancel_cleanup:
            owner.cancel()
            await asyncio.sleep(0)
            owner.cancel()
            await asyncio.sleep(0)
        state.request_uuid_lock.release()
        lock_held = False
        expected_error = asyncio.CancelledError if cancel_cleanup else RuntimeError
        with pytest.raises(expected_error):
            await asyncio.wait_for(owner, 1)
        assert not state.request_uuid_inflight
        with pytest.raises(RuntimeError, match="moderation failed"):
            await asyncio.wait_for(waiter, 1)
        assert cleanup_calls == 1  # 等待者不拥有失败请求，不能再清理该 UUID。
        assert not state.send_inflight
        assert not store._active_deliveries
        assert sender.group_messages == []
        retry = await send()
        assert retry.status == 200
        assert sender.group_messages == [(456, "hello")]
        assert security.calls == 2
    finally:
        release_moderation.set()
        if lock_held:
            state.request_uuid_lock.release()
        pending = [owner, *([waiter] if waiter is not None else [])]
        for task in pending:
            if not task.done():
                task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        await server.stop()


@pytest.mark.asyncio
async def test_naga_cancelled_uuid_waiter_keeps_owner_and_other_waiters(
    tmp_path: Path,
) -> None:
    entered = asyncio.Event()
    release = asyncio.Event()

    class _Security:
        calls = 0

        async def moderate_naga_message(
            self, *, message_format: str, content: str
        ) -> NagaModerationResult:
            self.calls += 1
            entered.set()
            await release.wait()
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
        bind_uuid="uuid_a", naga_id="alice", delivery_signature="sig_1"
    )
    sender = _FakeSender()
    security = _Security()
    server = _make_server(store=store, sender=sender, security=security)
    body: dict[str, Any] = {
        "bind_uuid": "uuid_a",
        "naga_id": "alice",
        "delivery_signature": "sig_1",
        "uuid": "req-cancelled-waiter",
        "target": {"qq_id": 123, "group_id": 456, "mode": "group"},
        "message": {"format": "text", "content": "hello"},
    }

    async def send() -> Response:
        return await server._naga_messages_send_handler(
            _make_request(
                json_body=body, headers={"Authorization": "Bearer shared-key"}
            )
        )

    owner = asyncio.create_task(send())
    tasks = [owner]
    try:
        await asyncio.wait_for(entered.wait(), 1)
        cancelled_waiter = asyncio.create_task(send())
        tasks.append(cancelled_waiter)
        await asyncio.sleep(0)
        cancelled_waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(cancelled_waiter, 1)
        future = server._naga_state.request_uuid_inflight[body["uuid"]][1]
        assert not future.done()
        assert not owner.done()
        other_waiter = asyncio.create_task(send())
        tasks.append(other_waiter)
        await asyncio.sleep(0)
        release.set()
        first, second = await asyncio.wait_for(asyncio.gather(owner, other_waiter), 1)
        assert first.status == second.status == 200
        assert _json(first) == _json(second)
        assert sender.group_messages == [(456, "hello")]
        assert security.calls == 1
        assert not server._naga_state.request_uuid_inflight
        assert not server._naga_state.send_inflight
    finally:
        release.set()
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await server.stop()


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
    naga = server._ctx.config_getter().naga
    naga.allowed_group_ids = frozenset()
    naga.is_group_allowed = lambda gid: False

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
    assert payload["error"] == "naga policy denied"


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
