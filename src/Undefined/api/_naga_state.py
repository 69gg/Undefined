"""Naga request deduplication and inflight tracking state."""

from __future__ import annotations

import asyncio
import time
from copy import deepcopy
from typing import Any

from ._helpers import _NagaRequestResult

_NAGA_REQUEST_UUID_TTL_SECONDS = 6 * 60 * 60


class NagaState:
    """Tracks inflight Naga sends and provides request-uuid deduplication."""

    def __init__(self) -> None:
        self.send_registry_lock = asyncio.Lock()
        self.send_inflight: dict[str, int] = {}
        self.request_uuid_lock = asyncio.Lock()
        self.request_uuid_inflight: dict[
            str, tuple[str, asyncio.Future[tuple[int, dict[str, Any]]]]
        ] = {}
        self.request_uuid_results: dict[str, _NagaRequestResult] = {}

    async def track_send_start(self, message_key: str) -> int:
        async with self.send_registry_lock:
            next_count = self.send_inflight.get(message_key, 0) + 1
            self.send_inflight[message_key] = next_count
            return next_count

    async def track_send_done(self, message_key: str) -> int:
        async with self.send_registry_lock:
            current = self.send_inflight.get(message_key, 0)
            if current <= 1:
                self.send_inflight.pop(message_key, None)
                return 0
            next_count = current - 1
            self.send_inflight[message_key] = next_count
            return next_count

    def _prune_request_uuid_state_locked(self) -> None:
        now = time.time()
        expired = [
            request_uuid
            for request_uuid, result in self.request_uuid_results.items()
            if now - result.finished_at > _NAGA_REQUEST_UUID_TTL_SECONDS
        ]
        for request_uuid in expired:
            self.request_uuid_results.pop(request_uuid, None)

    async def register_request_uuid(
        self, request_uuid: str, payload_hash: str
    ) -> tuple[str, Any]:
        async with self.request_uuid_lock:
            self._prune_request_uuid_state_locked()

            cached = self.request_uuid_results.get(request_uuid)
            if cached is not None:
                if cached.payload_hash != payload_hash:
                    return "conflict", cached.payload_hash
                return "cached", (cached.status, deepcopy(cached.payload))

            inflight = self.request_uuid_inflight.get(request_uuid)
            if inflight is not None:
                existing_hash, inflight_future = inflight
                if existing_hash != payload_hash:
                    return "conflict", existing_hash
                return "await", inflight_future

            owner_future: asyncio.Future[tuple[int, dict[str, Any]]] = (
                asyncio.get_running_loop().create_future()
            )
            self.request_uuid_inflight[request_uuid] = (
                payload_hash,
                owner_future,
            )
            return "owner", owner_future

    async def finish_request_uuid(
        self,
        request_uuid: str,
        payload_hash: str,
        *,
        status: int,
        payload: dict[str, Any],
    ) -> None:
        async with self.request_uuid_lock:
            inflight = self.request_uuid_inflight.pop(request_uuid, None)
            future = inflight[1] if inflight is not None else None
            result_payload = deepcopy(payload)
            self.request_uuid_results[request_uuid] = _NagaRequestResult(
                payload_hash=payload_hash,
                status=status,
                payload=result_payload,
                finished_at=time.time(),
            )
            self._prune_request_uuid_state_locked()
            if future is not None and not future.done():
                future.set_result((status, deepcopy(result_payload)))

    async def fail_request_uuid(
        self,
        request_uuid: str,
        payload_hash: str,
        exc: BaseException,
    ) -> None:
        _ = payload_hash
        async with self.request_uuid_lock:
            inflight = self.request_uuid_inflight.pop(request_uuid, None)
            future = inflight[1] if inflight is not None else None
            self._prune_request_uuid_state_locked()
            if future is not None and not future.done():
                future.set_exception(exc)
