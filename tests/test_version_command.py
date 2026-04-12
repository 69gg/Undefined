from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from Undefined.changelog import ChangelogEntry, ChangelogError
from Undefined.services.command import CommandDispatcher
from Undefined.services.commands.context import CommandContext
from Undefined.services.commands.registry import CommandRegistry
from Undefined.skills.commands.version import handler as version_handler


class _DummySender:
    def __init__(self) -> None:
        self.messages: list[tuple[int, str, bool]] = []
        self.private_messages: list[tuple[int, str, bool]] = []

    async def send_group_message(
        self, group_id: int, message: str, mark_sent: bool = False
    ) -> None:
        self.messages.append((group_id, message, mark_sent))

    async def send_private_message(
        self,
        user_id: int,
        message: str,
        auto_history: bool = True,
        *,
        mark_sent: bool = True,
    ) -> None:
        _ = auto_history
        self.private_messages.append((user_id, message, mark_sent))


def _build_context(
    sender: _DummySender,
    *,
    group_id: int = 10001,
    scope: str = "group",
    user_id: int | None = None,
) -> CommandContext:
    stub = cast(Any, SimpleNamespace())
    return CommandContext(
        group_id=group_id,
        sender_id=10002,
        config=cast(Any, SimpleNamespace(bot_qq=10000)),
        sender=cast(Any, sender),
        ai=stub,
        faq_storage=stub,
        onebot=cast(Any, SimpleNamespace(send_forward_msg=None)),
        security=stub,
        queue_manager=None,
        rate_limiter=None,
        dispatcher=stub,
        registry=CommandRegistry(Path("/tmp/not-used")),
        scope=scope,
        user_id=user_id,
    )


def _entry(version: str, title: str) -> ChangelogEntry:
    return ChangelogEntry(
        version=version,
        title=title,
        summary=f"{title} 摘要",
        changes=(f"{title} 变更一",),
    )


# -- 功能测试 --


@pytest.mark.asyncio
async def test_version_shows_version_and_changelog_title(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sender = _DummySender()
    context = _build_context(sender)
    entry = _entry("v3.3.0", "持久化表情包库与提示词调优")
    monkeypatch.setattr(version_handler, "get_latest_entry", lambda: entry)
    monkeypatch.setattr(version_handler, "__version__", "3.3.0")

    await version_handler.execute([], context)

    text = sender.messages[-1][1]
    assert "Undefined v3.3.0" in text
    assert "v3.3.0" in text
    assert "持久化表情包库与提示词调优" in text


@pytest.mark.asyncio
async def test_version_fallback_on_changelog_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sender = _DummySender()
    context = _build_context(sender)

    def _raise() -> None:
        raise ChangelogError("not found")

    monkeypatch.setattr(version_handler, "get_latest_entry", _raise)
    monkeypatch.setattr(version_handler, "__version__", "3.3.0")

    await version_handler.execute([], context)

    text = sender.messages[-1][1]
    assert "Undefined v3.3.0" in text
    assert "最新版本" not in text


@pytest.mark.asyncio
async def test_version_private_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sender = _DummySender()
    context = _build_context(sender, scope="private", user_id=99999)
    entry = _entry("v3.3.0", "测试标题")
    monkeypatch.setattr(version_handler, "get_latest_entry", lambda: entry)
    monkeypatch.setattr(version_handler, "__version__", "3.3.0")

    await version_handler.execute([], context)

    assert len(sender.private_messages) == 1
    text = sender.private_messages[-1][1]
    assert "Undefined v3.3.0" in text


# -- 注册测试 --


def test_version_command_registered() -> None:
    dispatcher = CommandDispatcher(
        config=cast(
            Any,
            SimpleNamespace(is_superadmin=lambda _x: False, is_admin=lambda _x: False),
        ),
        sender=cast(Any, _DummySender()),
        ai=cast(Any, SimpleNamespace()),
        faq_storage=cast(Any, SimpleNamespace()),
        onebot=cast(Any, SimpleNamespace()),
        security=cast(Any, SimpleNamespace(rate_limiter=None)),
    )

    meta = dispatcher.command_registry.resolve("version")
    assert meta is not None
    assert meta.allow_in_private is True
    assert "v" in meta.aliases

    meta_alias = dispatcher.command_registry.resolve("v")
    assert meta_alias is not None
    assert meta_alias.name == "version"
