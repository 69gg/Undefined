from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from Undefined.api.naga_store import NagaStore
from Undefined.services.commands.context import CommandContext
from Undefined.services.commands.registry import CommandRegistry
from Undefined.skills.commands.help.handler import execute as help_execute
from Undefined.skills.commands.naga import handler as naga_handler


_COMMANDS_DIR = Path(__file__).resolve().parents[1] / "src/Undefined/skills/commands"


class _DummySender:
    def __init__(self) -> None:
        self.group_messages: list[tuple[int, str]] = []
        self.private_messages: list[tuple[int, str]] = []

    async def send_group_message(self, group_id: int, message: str, **_: Any) -> None:
        self.group_messages.append((group_id, message))

    async def send_private_message(self, user_id: int, message: str, **_: Any) -> None:
        self.private_messages.append((user_id, message))


class _DummyOneBot:
    async def get_group_info(self, group_id: int) -> dict[str, Any]:
        return {"data": {"group_name": f"group-{group_id}"}}

    async def get_stranger_info(self, user_id: int) -> dict[str, Any]:
        return {"data": {"nickname": f"user-{user_id}", "remark": ""}}


def _config(
    *,
    allowed_groups: set[int],
    superadmin: bool = False,
    api_enabled: bool = True,
) -> Any:
    return SimpleNamespace(
        api=SimpleNamespace(enabled=api_enabled),
        nagaagent_mode_enabled=True,
        naga=SimpleNamespace(
            enabled=True,
            allowed_groups=allowed_groups,
            api_url="https://naga.example.com",
            api_key="shared-key",
        ),
        bot_qq=42,
        is_superadmin=lambda sender_id: superadmin and sender_id == 1,
        is_admin=lambda sender_id: superadmin and sender_id == 1,
    )


def _context(
    *,
    sender: _DummySender,
    registry: CommandRegistry,
    scope: str,
    group_id: int,
    sender_id: int = 1,
    user_id: int | None = None,
    superadmin: bool = False,
    allowed_groups: set[int] | None = None,
    store: NagaStore | None = None,
) -> CommandContext:
    allowed_groups = allowed_groups or set()
    dispatcher = SimpleNamespace(sender=sender, naga_store=store)
    return CommandContext(
        group_id=group_id,
        sender_id=sender_id,
        config=cast(Any, _config(allowed_groups=allowed_groups, superadmin=superadmin)),
        sender=cast(Any, sender),
        ai=cast(Any, SimpleNamespace()),
        faq_storage=cast(Any, SimpleNamespace()),
        onebot=cast(Any, _DummyOneBot()),
        security=cast(Any, SimpleNamespace()),
        queue_manager=None,
        rate_limiter=None,
        dispatcher=cast(Any, dispatcher),
        registry=registry,
        scope=scope,
        user_id=user_id,
    )


@pytest.fixture
def registry() -> CommandRegistry:
    registry = CommandRegistry(_COMMANDS_DIR)
    registry.load_commands()
    return registry


@pytest.mark.asyncio
async def test_naga_hidden_from_help_in_non_allowlisted_group(
    registry: CommandRegistry,
) -> None:
    sender = _DummySender()
    context = _context(
        sender=sender,
        registry=registry,
        scope="group",
        group_id=999,
        allowed_groups={123},
    )

    await help_execute([], context)

    assert sender.group_messages
    output = sender.group_messages[-1][1]
    assert "/naga <子命令>" not in output


@pytest.mark.asyncio
async def test_naga_visible_in_help_for_superadmin_private(
    registry: CommandRegistry,
) -> None:
    sender = _DummySender()
    context = _context(
        sender=sender,
        registry=registry,
        scope="private",
        group_id=0,
        user_id=1,
        superadmin=True,
        allowed_groups={123},
    )

    await help_execute([], context)

    assert sender.group_messages
    output = sender.group_messages[-1][1]
    assert "/naga <bind|unbind> [参数]" in output


@pytest.mark.asyncio
async def test_naga_hidden_when_runtime_api_disabled(
    registry: CommandRegistry,
) -> None:
    sender = _DummySender()
    context = _context(
        sender=sender,
        registry=registry,
        scope="private",
        group_id=0,
        user_id=1,
        superadmin=True,
        allowed_groups={123},
    )
    context.config.api.enabled = False

    await help_execute([], context)

    assert sender.group_messages
    output = sender.group_messages[-1][1]
    assert "/naga <bind|unbind> [参数]" not in output


@pytest.mark.asyncio
async def test_naga_execute_silent_in_non_allowlisted_group(
    registry: CommandRegistry,
    tmp_path: Path,
) -> None:
    sender = _DummySender()
    store = NagaStore(tmp_path / "naga_bindings.json")
    context = _context(
        sender=sender,
        registry=registry,
        scope="group",
        group_id=999,
        allowed_groups={123},
        store=store,
    )

    await naga_handler.execute(["bind", "alice"], context)

    assert sender.group_messages == []
    assert sender.private_messages == []
    assert store.list_pending() == []


@pytest.mark.asyncio
async def test_naga_bind_submits_pending_and_replies(
    registry: CommandRegistry,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sender = _DummySender()
    store = NagaStore(tmp_path / "naga_bindings.json")
    context = _context(
        sender=sender,
        registry=registry,
        scope="group",
        group_id=123,
        allowed_groups={123},
        store=store,
    )

    async def _accepted(*_: Any, **__: Any) -> tuple[str, str]:
        return "accepted", "HTTP 202"

    monkeypatch.setattr(naga_handler, "_submit_bind_request_to_naga", _accepted)

    await naga_handler.execute(["bind", "alice"], context)

    pending = store.get_pending("alice")
    assert pending is not None
    assert sender.group_messages
    assert "等待 Naga 端确认" in sender.group_messages[-1][1]


@pytest.mark.asyncio
async def test_naga_bind_reuses_existing_pending_without_duplicate_submit(
    registry: CommandRegistry,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sender = _DummySender()
    store = NagaStore(tmp_path / "naga_bindings.json")
    context = _context(
        sender=sender,
        registry=registry,
        scope="group",
        group_id=123,
        allowed_groups={123},
        store=store,
    )
    calls = 0

    async def _accepted(*_: Any, **__: Any) -> tuple[str, str]:
        nonlocal calls
        calls += 1
        return "accepted", "HTTP 202"

    monkeypatch.setattr(naga_handler, "_submit_bind_request_to_naga", _accepted)

    await naga_handler.execute(["bind", "alice"], context)
    first_pending = store.get_pending("alice")
    assert first_pending is not None

    await naga_handler.execute(["bind", "alice"], context)
    second_pending = store.get_pending("alice")
    assert second_pending is not None
    assert second_pending.bind_uuid == first_pending.bind_uuid
    assert calls == 1
    assert "已在处理中" in sender.group_messages[-1][1]


@pytest.mark.asyncio
async def test_naga_bind_keeps_pending_on_transport_error(
    registry: CommandRegistry,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sender = _DummySender()
    store = NagaStore(tmp_path / "naga_bindings.json")
    context = _context(
        sender=sender,
        registry=registry,
        scope="group",
        group_id=123,
        allowed_groups={123},
        store=store,
    )

    async def _transport_error(*_: Any, **__: Any) -> tuple[str, str]:
        return "transport_error", "timeout"

    monkeypatch.setattr(naga_handler, "_submit_bind_request_to_naga", _transport_error)

    await naga_handler.execute(["bind", "alice"], context)

    pending = store.get_pending("alice")
    assert pending is not None
    assert "已保留在本地" in sender.group_messages[-1][1]


@pytest.mark.asyncio
async def test_naga_unbind_in_private_for_superadmin(
    registry: CommandRegistry,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sender = _DummySender()
    store = NagaStore(tmp_path / "naga_bindings.json")
    await store.submit_binding("alice", qq_id=321, group_id=123, bind_uuid="uuid_a")
    await store.activate_binding(
        bind_uuid="uuid_a",
        naga_id="alice",
        delivery_signature="sig_1",
    )
    context = _context(
        sender=sender,
        registry=registry,
        scope="private",
        group_id=0,
        user_id=1,
        superadmin=True,
        allowed_groups={123},
        store=store,
    )

    async def _synced(*_: Any, **__: Any) -> bool:
        return True

    monkeypatch.setattr(naga_handler, "_notify_remote_revoke", _synced)

    await naga_handler.execute(["unbind", "alice"], context)

    binding = store.get_binding("alice")
    assert binding is not None
    assert binding.revoked is True
    assert sender.private_messages
    assert any("已解绑" in message for _, message in sender.private_messages)
