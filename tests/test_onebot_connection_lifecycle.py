"""OneBot reconnect does not wait for unrelated message work."""

from __future__ import annotations

import asyncio
import json
from typing import Any, cast

import pytest
from websockets.exceptions import ConnectionClosedOK

from Undefined.onebot.client import OneBotClient


class _WebSocket:
    def __init__(self, handler_started: asyncio.Event | None = None) -> None:
        self.handler_started = handler_started
        self.sent_message = False
        self.closed = asyncio.Event()

    async def recv(self) -> str:
        if self.handler_started is not None:
            if not self.sent_message:
                self.sent_message = True
                return json.dumps({"post_type": "message", "message_type": "group"})
            await self.handler_started.wait()
        else:
            await self.closed.wait()
        raise ConnectionClosedOK(None, None)

    async def close(self) -> None:
        self.closed.set()


@pytest.mark.asyncio
async def test_reconnect_preserves_inflight_handler_without_waiting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = OneBotClient("ws://example.invalid")
    started = asyncio.Event()
    release = asyncio.Event()
    finished = asyncio.Event()
    reconnected = asyncio.Event()
    connections = 0

    async def handler(data: dict[str, Any]) -> None:
        started.set()
        await release.wait()
        finished.set()

    async def connect() -> None:
        nonlocal connections
        connections += 1
        client.ws = cast(Any, _WebSocket(started if connections == 1 else None))
        if connections == 2:
            reconnected.set()

    client.set_message_handler(handler)
    monkeypatch.setattr(client, "connect", connect)
    pending: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
    client._pending_responses["waiting"] = pending
    running = asyncio.create_task(client.run_with_reconnect(reconnect_interval=0))
    try:
        await asyncio.wait_for(reconnected.wait(), 1)
        assert connections == 2
        assert len(client._tasks) == 1
        assert not finished.is_set()
        assert isinstance(pending.exception(), ConnectionError)
        release.set()
        await asyncio.wait_for(finished.wait(), 1)
        await asyncio.sleep(0)
        assert not client._tasks
    finally:
        release.set()
        running.cancel()
        await asyncio.gather(running, return_exceptions=True)
        await client.disconnect()


@pytest.mark.asyncio
@pytest.mark.parametrize("disconnect", [False, True])
async def test_shutdown_cancels_and_collects_message_handlers(disconnect: bool) -> None:
    client = OneBotClient("ws://example.invalid")
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def handler(data: dict[str, Any]) -> None:
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    client.set_message_handler(handler)
    client.ws = cast(Any, _WebSocket())
    await client._dispatch_message({"post_type": "message"})
    running = asyncio.create_task(client.run())
    await asyncio.wait_for(started.wait(), 1)
    if disconnect:
        await asyncio.wait_for(client.disconnect(), 1)
        await asyncio.wait_for(running, 1)
    else:
        running.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(running, 1)
    assert cancelled.is_set()
    assert not client._tasks


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["sleep", "connect"])
async def test_reconnect_gap_cancellation_collects_previous_handlers(
    monkeypatch: pytest.MonkeyPatch, phase: str
) -> None:
    client = OneBotClient("ws://example.invalid")
    started = asyncio.Event()
    cancelled = asyncio.Event()
    gap = asyncio.Event()
    connections = 0
    original_run = client.run

    async def handler(data: dict[str, Any]) -> None:
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    async def connect() -> None:
        nonlocal connections
        connections += 1
        if connections == 1:
            client.ws = cast(Any, _WebSocket(started))
        else:
            gap.set()
            await asyncio.Event().wait()

    async def run() -> None:
        await original_run()
        if phase == "sleep":
            gap.set()

    client.set_message_handler(handler)
    monkeypatch.setattr(client, "connect", connect)
    monkeypatch.setattr(client, "run", run)
    running = asyncio.create_task(
        client.run_with_reconnect(reconnect_interval=60 if phase == "sleep" else 0)
    )
    try:
        await asyncio.wait_for(gap.wait(), 1)
        assert client._tasks
        assert not cancelled.is_set()
        running.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(running, 1)
        assert cancelled.is_set()
        assert not client._tasks
    finally:
        running.cancel()
        await asyncio.gather(running, return_exceptions=True)
        await client.disconnect()
