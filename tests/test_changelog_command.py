from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

from Undefined.changelog import ChangelogError, ChangelogEntry
from Undefined.services.command import CommandDispatcher
from Undefined.services.commands.context import CommandContext
from Undefined.services.commands.registry import CommandRegistry
from Undefined.skills.commands.changelog import handler as changelog_handler


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
    onebot: Any | None = None,
    config: Any | None = None,
) -> CommandContext:
    stub = cast(Any, SimpleNamespace())
    resolved_onebot = (
        onebot
        if onebot is not None
        else cast(Any, SimpleNamespace(send_forward_msg=None))
    )
    resolved_config = (
        config if config is not None else cast(Any, SimpleNamespace(bot_qq=10000))
    )
    return CommandContext(
        group_id=group_id,
        sender_id=10002,
        config=resolved_config,
        sender=cast(Any, sender),
        ai=stub,
        faq_storage=stub,
        onebot=resolved_onebot,
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
    assert "/changelog <version>" in output


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
async def test_changelog_command_inferrs_show_for_direct_version_argument(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sender = _DummySender()
    context = _build_context(sender)
    monkeypatch.setattr(
        changelog_handler,
        "get_entry",
        lambda version: _entry("v3.2.6", "标题甲"),
    )

    await changelog_handler.execute(["V3.2.6"], context)

    output = sender.messages[-1][1]
    assert output.startswith("v3.2.6 标题甲")
    assert "标题甲 摘要" in output


@pytest.mark.asyncio
async def test_changelog_command_inferrs_list_for_direct_limit_argument(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sender = _DummySender()
    context = _build_context(sender)
    captured: dict[str, int] = {}

    def _list_entries(*, limit: int) -> tuple[ChangelogEntry, ...]:
        captured["limit"] = limit
        return (_entry("v3.2.6", "标题甲"),)

    monkeypatch.setattr(changelog_handler, "list_entries", _list_entries)

    await changelog_handler.execute(["12"], context)

    assert captured["limit"] == 12
    assert "- v3.2.6 | 标题甲" in sender.messages[-1][1]


@pytest.mark.asyncio
async def test_changelog_command_large_list_uses_forward_in_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sender = _DummySender()
    onebot = cast(Any, SimpleNamespace(send_forward_msg=AsyncMock()))
    context = _build_context(sender, onebot=onebot)
    monkeypatch.setattr(
        changelog_handler,
        "list_entries",
        lambda *, limit: tuple(_entry(f"v3.2.{idx}", f"标题{idx}") for idx in range(6)),
    )

    await changelog_handler.execute(["list", "25"], context)

    assert not sender.messages
    onebot.send_forward_msg.assert_awaited_once()
    group_id, nodes = onebot.send_forward_msg.await_args.args
    assert group_id == 10001
    assert nodes[0]["data"]["content"].startswith("Undefined CHANGELOG")
    assert "1. v3.2.0 | 标题0" in nodes[1]["data"]["content"]


@pytest.mark.asyncio
async def test_changelog_command_large_list_uses_private_sender_in_private_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sender = _DummySender()
    onebot = cast(Any, SimpleNamespace(send_forward_msg=AsyncMock()))
    context = _build_context(
        sender,
        group_id=0,
        scope="private",
        user_id=20001,
        onebot=onebot,
    )
    monkeypatch.setattr(
        changelog_handler,
        "list_entries",
        lambda *, limit: (_entry("v3.2.6", "标题甲"), _entry("v3.2.5", "标题乙")),
    )

    await changelog_handler.execute(["25"], context)

    assert not sender.messages
    assert sender.private_messages[-1][0] == 20001
    assert "Undefined CHANGELOG" in sender.private_messages[-1][1]
    onebot.send_forward_msg.assert_not_awaited()


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
async def test_changelog_command_latest_uses_private_sender_in_private_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sender = _DummySender()
    context = _build_context(sender, group_id=0, scope="private", user_id=20001)
    monkeypatch.setattr(
        changelog_handler,
        "get_latest_entry",
        lambda: _entry("v3.2.6", "标题甲"),
    )

    await changelog_handler.execute(["latest"], context)

    assert not sender.messages
    assert sender.private_messages[-1][0] == 20001
    assert sender.private_messages[-1][1].startswith("v3.2.6 标题甲")


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
    assert dispatcher.command_registry.resolve("cl") is not None
