from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from Undefined.changelog import ChangelogError, ChangelogEntry
from Undefined.services.command import CommandDispatcher
from Undefined.services.commands.context import CommandContext
from Undefined.services.commands.registry import CommandRegistry
from Undefined.skills.commands.changelog import handler as changelog_handler


class _DummySender:
    def __init__(self) -> None:
        self.messages: list[tuple[int, str, bool]] = []

    async def send_group_message(
        self, group_id: int, message: str, mark_sent: bool = False
    ) -> None:
        self.messages.append((group_id, message, mark_sent))


def _build_context(sender: _DummySender) -> CommandContext:
    stub = cast(Any, SimpleNamespace())
    return CommandContext(
        group_id=10001,
        sender_id=10002,
        config=stub,
        sender=cast(Any, sender),
        ai=stub,
        faq_storage=stub,
        onebot=stub,
        security=stub,
        queue_manager=None,
        rate_limiter=None,
        dispatcher=stub,
        registry=CommandRegistry(Path("/tmp/not-used")),
    )


def _entry(version: str, title: str) -> ChangelogEntry:
    return ChangelogEntry(
        version=version,
        title=title,
        summary=f"{title} 摘要",
        changes=(f"{title} 变更一", f"{title} 变更二", f"{title} 变更三"),
    )


@pytest.mark.asyncio
async def test_changelog_command_lists_recent_versions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sender = _DummySender()
    context = _build_context(sender)
    monkeypatch.setattr(
        changelog_handler,
        "list_entries",
        lambda limit: (_entry("v3.2.6", "标题甲"), _entry("v3.2.5", "标题乙"))[:limit],
    )

    await changelog_handler.execute([], context)

    output = sender.messages[-1][1]
    assert "Undefined CHANGELOG" in output
    assert "- v3.2.6 | 标题甲" in output
    assert "- v3.2.5 | 标题乙" in output
    assert "/changelog show <version>" in output


@pytest.mark.asyncio
async def test_changelog_command_show_supports_version_argument(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sender = _DummySender()
    context = _build_context(sender)
    monkeypatch.setattr(
        changelog_handler,
        "get_entry",
        lambda version: _entry("v3.2.6", "标题甲"),
    )

    await changelog_handler.execute(["show", "3.2.6"], context)

    output = sender.messages[-1][1]
    assert output.startswith("v3.2.6 标题甲")
    assert "标题甲 摘要" in output
    assert "- 标题甲 变更一" in output


@pytest.mark.asyncio
async def test_changelog_command_latest_uses_first_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sender = _DummySender()
    context = _build_context(sender)
    monkeypatch.setattr(
        changelog_handler,
        "get_latest_entry",
        lambda: _entry("v3.2.6", "标题甲"),
    )

    await changelog_handler.execute(["latest"], context)

    assert sender.messages[-1][1].startswith("v3.2.6 标题甲")


@pytest.mark.asyncio
async def test_changelog_command_reports_lookup_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sender = _DummySender()
    context = _build_context(sender)

    def _raise(_: str) -> ChangelogEntry:
        raise ChangelogError("未找到版本: v9.9.9")

    monkeypatch.setattr(changelog_handler, "get_entry", _raise)

    await changelog_handler.execute(["show", "v9.9.9"], context)

    assert sender.messages[-1][1] == "❌ 未找到版本: v9.9.9"


def test_changelog_command_is_registered_for_private_use() -> None:
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

    meta = dispatcher.command_registry.resolve("changelog")
    assert meta is not None
    assert meta.allow_in_private is True
    assert meta.rate_limit.user == 5
