"""Undefined 自有的会话映射和路由日志；协议队列始终由 ClientStore 管理。"""

from __future__ import annotations

import asyncio
import copy
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar

from Undefined.utils import io

_T = TypeVar("_T")


class ChannelJournal:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = asyncio.Lock()
        self.data: dict[str, Any] = {
            "routes": {},
            "aliases": {},
            "events": {},
            "tasks": {},
            "cursor": 0,
            "cursors": {},
        }

    async def open(self) -> None:
        raw = await io.read_json(self.path)
        if isinstance(raw, dict):
            self.data.update(raw)
        for event in self.data["events"].values():
            if event.get("state") == "processing":
                event["state"] = (
                    "received" if event.get("delivery") == "pending" else "interrupted"
                )
            if event.get("delivery") == "processing":
                event["delivery"] = "uncertain"
        await self.update(lambda data: None)

    async def update(self, change: Callable[[dict[str, Any]], _T]) -> _T:
        async with self._lock:
            data = copy.deepcopy(self.data)
            result = change(data)

            async def commit() -> None:
                await io.write_json(self.path, data)
                self.data = data

            await io.run_cancellation_safe(commit())
            return result

    async def put(self, collection: str, key: str, value: dict[str, Any]) -> None:
        await self.update(lambda data: data[collection].__setitem__(key, value))
