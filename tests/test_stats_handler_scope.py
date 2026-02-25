from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest

from Undefined.services.commands.context import CommandContext
from Undefined.skills.commands.stats.handler import execute


class _DummyDispatcher:
    def __init__(self) -> None:
        self.group_calls: list[tuple[int, int, list[str]]] = []
        self.private_calls: list[tuple[int, int, list[str], bool, bool]] = []

    async def _handle_stats(
        self, group_id: int, sender_id: int, args: list[str]
    ) -> None:
        self.group_calls.append((group_id, sender_id, list(args)))

    async def _handle_stats_private(
        self,
        user_id: int,
        sender_id: int,
        args: list[str],
        send_message: Any = None,
        *,
        is_webui_session: bool = False,
    ) -> None:
        self.private_calls.append(
            (
                user_id,
                sender_id,
                list(args),
                callable(send_message),
                is_webui_session,
            )
        )


class _DummyPrivateSender:
    async def send_private_message(self, _user_id: int, _message: str) -> None:
        return None


def _build_context(
    *,
    dispatcher: _DummyDispatcher,
    scope: str,
    group_id: int,
    sender_id: int,
    user_id: int | None = None,
    is_webui_session: bool = False,
) -> CommandContext:
    return CommandContext(
        group_id=group_id,
        sender_id=sender_id,
        config=cast(Any, SimpleNamespace()),
        sender=cast(Any, _DummyPrivateSender()),
        ai=cast(Any, SimpleNamespace()),
        faq_storage=cast(Any, SimpleNamespace()),
        onebot=cast(Any, SimpleNamespace()),
        security=cast(Any, SimpleNamespace()),
        queue_manager=cast(Any, None),
        rate_limiter=cast(Any, None),
        dispatcher=cast(Any, dispatcher),
        registry=cast(Any, SimpleNamespace()),
        scope=scope,
        user_id=user_id,
        is_webui_session=is_webui_session,
    )


@pytest.mark.asyncio
async def test_stats_handler_routes_group_scope() -> None:
    dispatcher = _DummyDispatcher()
    context = _build_context(
        dispatcher=dispatcher,
        scope="group",
        group_id=12345,
        sender_id=10001,
    )

    await execute(["7d"], context)

    assert dispatcher.group_calls == [(12345, 10001, ["7d"])]
    assert dispatcher.private_calls == []


@pytest.mark.asyncio
async def test_stats_handler_routes_private_scope_with_webui_flag() -> None:
    dispatcher = _DummyDispatcher()
    context = _build_context(
        dispatcher=dispatcher,
        scope="private",
        group_id=0,
        sender_id=90001,
        user_id=42,
        is_webui_session=True,
    )

    await execute(["30d", "--ai"], context)

    assert dispatcher.group_calls == []
    assert dispatcher.private_calls == [
        (
            42,
            90001,
            ["30d", "--ai"],
            True,
            True,
        )
    ]
