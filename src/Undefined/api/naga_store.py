"""Naga 绑定存储。"""

from __future__ import annotations

import asyncio
import logging
import os
import secrets
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal, cast
from uuid import uuid4

from Undefined.utils.io import read_json, write_json

logger = logging.getLogger(__name__)

_STORE_VERSION = 3
_DATA_FILE = Path("data/naga_bindings.json")
_PENDING_TTL_SECONDS = 24 * 60 * 60
_TERMINAL_RECORD_RETENTION_SECONDS = 30 * 24 * 60 * 60

CompletedRequestStatus = Literal["rejected", "cancelled", "expired"]


@dataclass
class NagaBinding:
    """当前代的 Naga 绑定。"""

    naga_id: str
    bind_uuid: str
    delivery_signature: str
    qq_id: int
    group_id: int
    created_at: float
    revoked: bool = False
    revoked_at: float | None = None
    description: str = ""
    last_used_at: float | None = None
    use_count: int = 0


@dataclass
class PendingBinding:
    """待远端确认的绑定申请。"""

    naga_id: str
    bind_uuid: str
    qq_id: int
    group_id: int
    requested_at: float
    request_context: dict[str, Any] = field(default_factory=dict)
    submit_attempts: int = 0
    last_submit_attempt_at: float | None = None


@dataclass
class HistoricalBinding:
    """按 bind_uuid 持久化的绑定历史，用于幂等和审计。"""

    naga_id: str
    bind_uuid: str
    delivery_signature: str
    qq_id: int
    group_id: int
    created_at: float
    revoked: bool = False
    revoked_at: float | None = None
    last_used_at: float | None = None
    use_count: int = 0


@dataclass
class CompletedBindRequest:
    """终态的绑定请求记录。"""

    naga_id: str
    bind_uuid: str
    qq_id: int
    group_id: int
    status: CompletedRequestStatus
    resolved_at: float
    reason: str = ""


def generate_bind_uuid() -> str:
    return uuid4().hex


def mask_token(token: str) -> str:
    """日志脱敏：只显示前 12 字符 + '...'。"""
    if len(token) <= 12:
        return token
    return token[:12] + "..."


def _clone_binding(binding: NagaBinding) -> NagaBinding:
    return NagaBinding(**asdict(binding))


def _clone_pending(pending: PendingBinding) -> PendingBinding:
    data = asdict(pending)
    data["request_context"] = dict(pending.request_context)
    return PendingBinding(**data)


def _clone_history(history: HistoricalBinding) -> HistoricalBinding:
    return HistoricalBinding(**asdict(history))


def _binding_from_history(history: HistoricalBinding) -> NagaBinding:
    return NagaBinding(
        naga_id=history.naga_id,
        bind_uuid=history.bind_uuid,
        delivery_signature=history.delivery_signature,
        qq_id=history.qq_id,
        group_id=history.group_id,
        created_at=history.created_at,
        revoked=history.revoked,
        revoked_at=history.revoked_at,
        last_used_at=history.last_used_at,
        use_count=history.use_count,
    )


class NagaStore:
    """Naga 绑定数据管理。"""

    def __init__(self, data_file: Path = _DATA_FILE) -> None:
        self._data_file = data_file
        self._bindings: dict[str, NagaBinding] = {}
        self._pending: dict[str, PendingBinding] = {}
        self._history: dict[str, HistoricalBinding] = {}
        self._completed_requests: dict[str, CompletedBindRequest] = {}
        self._active_deliveries: dict[str, int] = {}
        self._lock = asyncio.Lock()
        self._delivery_condition = asyncio.Condition(self._lock)

    async def load(self) -> None:
        raw = await read_json(self._data_file, use_lock=True)
        if raw is None:
            logger.info("[NagaStore] 绑定文件不存在，使用空数据")
            return
        if not isinstance(raw, dict):
            logger.warning("[NagaStore] 绑定文件格式错误，使用空数据")
            return

        self._bindings.clear()
        self._pending.clear()
        self._history.clear()
        self._completed_requests.clear()

        bindings_raw = raw.get("bindings", {})
        if isinstance(bindings_raw, dict):
            for naga_id, data in bindings_raw.items():
                if not isinstance(data, dict):
                    continue
                delivery_signature = str(
                    data.get("delivery_signature", data.get("token", ""))
                )
                self._bindings[naga_id] = NagaBinding(
                    naga_id=str(data.get("naga_id", naga_id)),
                    bind_uuid=str(data.get("bind_uuid", "")),
                    delivery_signature=delivery_signature,
                    qq_id=int(data.get("qq_id", 0)),
                    group_id=int(data.get("group_id", 0)),
                    created_at=float(data.get("created_at", 0)),
                    revoked=bool(data.get("revoked", False)),
                    revoked_at=(
                        float(data["revoked_at"])
                        if data.get("revoked_at") is not None
                        else None
                    ),
                    description=str(data.get("description", "")),
                    last_used_at=(
                        float(data["last_used_at"])
                        if data.get("last_used_at") is not None
                        else None
                    ),
                    use_count=int(data.get("use_count", 0)),
                )

        pending_raw = raw.get("pending", {})
        if isinstance(pending_raw, dict):
            for naga_id, data in pending_raw.items():
                if not isinstance(data, dict):
                    continue
                request_context = data.get("request_context", {})
                if not isinstance(request_context, dict):
                    request_context = {}
                self._pending[naga_id] = PendingBinding(
                    naga_id=str(data.get("naga_id", naga_id)),
                    bind_uuid=str(data.get("bind_uuid", "")),
                    qq_id=int(data.get("qq_id", 0)),
                    group_id=int(data.get("group_id", 0)),
                    requested_at=float(data.get("requested_at", 0)),
                    request_context=request_context,
                    submit_attempts=int(data.get("submit_attempts", 0)),
                    last_submit_attempt_at=(
                        float(data["last_submit_attempt_at"])
                        if data.get("last_submit_attempt_at") is not None
                        else None
                    ),
                )

        history_raw = raw.get("history", {})
        if isinstance(history_raw, dict):
            for bind_uuid, data in history_raw.items():
                if not isinstance(data, dict):
                    continue
                self._history[bind_uuid] = HistoricalBinding(
                    naga_id=str(data.get("naga_id", "")),
                    bind_uuid=str(data.get("bind_uuid", bind_uuid)),
                    delivery_signature=str(data.get("delivery_signature", "")),
                    qq_id=int(data.get("qq_id", 0)),
                    group_id=int(data.get("group_id", 0)),
                    created_at=float(data.get("created_at", 0)),
                    revoked=bool(data.get("revoked", False)),
                    revoked_at=(
                        float(data["revoked_at"])
                        if data.get("revoked_at") is not None
                        else None
                    ),
                    last_used_at=(
                        float(data["last_used_at"])
                        if data.get("last_used_at") is not None
                        else None
                    ),
                    use_count=int(data.get("use_count", 0)),
                )

        completed_raw = raw.get("completed_requests", {})
        if isinstance(completed_raw, dict):
            for bind_uuid, data in completed_raw.items():
                if not isinstance(data, dict):
                    continue
                status = str(data.get("status", "") or "").strip().lower()
                if status not in {"rejected", "cancelled", "expired"}:
                    continue
                status_literal = cast(CompletedRequestStatus, status)
                self._completed_requests[bind_uuid] = CompletedBindRequest(
                    naga_id=str(data.get("naga_id", "")),
                    bind_uuid=str(data.get("bind_uuid", bind_uuid)),
                    qq_id=int(data.get("qq_id", 0)),
                    group_id=int(data.get("group_id", 0)),
                    status=status_literal,
                    resolved_at=float(data.get("resolved_at", 0)),
                    reason=str(data.get("reason", "")),
                )

        needs_save = False
        for binding in self._bindings.values():
            if not binding.bind_uuid:
                continue
            if binding.bind_uuid in self._history:
                continue
            self._history[binding.bind_uuid] = HistoricalBinding(
                naga_id=binding.naga_id,
                bind_uuid=binding.bind_uuid,
                delivery_signature=binding.delivery_signature,
                qq_id=binding.qq_id,
                group_id=binding.group_id,
                created_at=binding.created_at,
                revoked=binding.revoked,
                revoked_at=binding.revoked_at,
                last_used_at=binding.last_used_at,
                use_count=binding.use_count,
            )
            needs_save = True

        now = time.time()
        if self._expire_pending_locked(now):
            needs_save = True
        if self._prune_terminal_records_locked(now):
            needs_save = True

        logger.info(
            "[NagaStore] 加载完成: bindings=%d pending=%d history=%d completed=%d",
            len(self._bindings),
            len(self._pending),
            len(self._history),
            len(self._completed_requests),
        )
        if needs_save:
            await self.save()
        await asyncio.to_thread(self._restrict_permissions)

    def _restrict_permissions(self) -> None:
        if os.name != "posix":
            return
        try:
            if self._data_file.exists():
                os.chmod(self._data_file, 0o600)
        except OSError as exc:
            logger.debug("[NagaStore] chmod 600 失败: %s", exc)

    def _expire_pending_locked(self, now: float) -> bool:
        dirty = False
        for naga_id, pending in list(self._pending.items()):
            if now - pending.requested_at < _PENDING_TTL_SECONDS:
                continue
            removed = self._pending.pop(naga_id)
            self._completed_requests[removed.bind_uuid] = CompletedBindRequest(
                naga_id=removed.naga_id,
                bind_uuid=removed.bind_uuid,
                qq_id=removed.qq_id,
                group_id=removed.group_id,
                status="expired",
                resolved_at=now,
                reason="pending bind expired",
            )
            logger.info(
                "[NagaStore] 待绑定过期: naga_id=%s qq=%d group=%d bind_uuid=%s",
                removed.naga_id,
                removed.qq_id,
                removed.group_id,
                removed.bind_uuid,
            )
            dirty = True
        return dirty

    def _prune_terminal_records_locked(self, now: float) -> bool:
        dirty = False
        for bind_uuid, completed in list(self._completed_requests.items()):
            if now - completed.resolved_at < _TERMINAL_RECORD_RETENTION_SECONDS:
                continue
            del self._completed_requests[bind_uuid]
            dirty = True

        current_bind_uuids = {binding.bind_uuid for binding in self._bindings.values()}
        for bind_uuid, history in list(self._history.items()):
            if bind_uuid in current_bind_uuids:
                continue
            if not history.revoked or history.revoked_at is None:
                continue
            if now - history.revoked_at < _TERMINAL_RECORD_RETENTION_SECONDS:
                continue
            del self._history[bind_uuid]
            dirty = True
        return dirty

    async def save(self) -> None:
        payload: dict[str, Any] = {
            "version": _STORE_VERSION,
            "bindings": {k: asdict(v) for k, v in self._bindings.items()},
            "pending": {k: asdict(v) for k, v in self._pending.items()},
            "history": {k: asdict(v) for k, v in self._history.items()},
            "completed_requests": {
                k: asdict(v) for k, v in self._completed_requests.items()
            },
        }
        await write_json(self._data_file, payload)
        await asyncio.to_thread(self._restrict_permissions)

    async def submit_binding(
        self,
        naga_id: str,
        qq_id: int,
        group_id: int,
        *,
        bind_uuid: str | None = None,
        request_context: dict[str, Any] | None = None,
    ) -> tuple[bool, str, PendingBinding | None]:
        async with self._lock:
            now = time.time()
            dirty = self._expire_pending_locked(now)
            dirty = self._prune_terminal_records_locked(now) or dirty

            active = self._bindings.get(naga_id)
            if active is not None and not active.revoked:
                if dirty:
                    await self.save()
                return False, f"naga_id '{naga_id}' 已绑定", None

            pending = self._pending.get(naga_id)
            if pending is not None:
                snapshot = _clone_pending(pending)
                if pending.qq_id == qq_id and pending.group_id == group_id:
                    if dirty:
                        await self.save()
                    return True, "申请已存在，等待 Naga 端确认", snapshot
                if dirty:
                    await self.save()
                return False, f"naga_id '{naga_id}' 已在处理中", None

            pending = PendingBinding(
                naga_id=naga_id,
                bind_uuid=str(bind_uuid or generate_bind_uuid()),
                qq_id=qq_id,
                group_id=group_id,
                requested_at=now,
                request_context=dict(request_context or {}),
            )
            self._pending[naga_id] = pending
            await self.save()
        return True, "申请已提交，等待 Naga 端确认", _clone_pending(pending)

    async def begin_remote_submit(
        self,
        naga_id: str,
        *,
        bind_uuid: str,
        cooldown_seconds: float = 3.0,
    ) -> tuple[PendingBinding | None, bool]:
        async with self._lock:
            now = time.time()
            pending = self._pending.get(naga_id)
            if pending is None or pending.bind_uuid != bind_uuid:
                return None, False
            if (
                pending.last_submit_attempt_at is not None
                and now - pending.last_submit_attempt_at < cooldown_seconds
            ):
                return _clone_pending(pending), False
            pending.last_submit_attempt_at = now
            pending.submit_attempts += 1
            return _clone_pending(pending), True

    async def activate_binding(
        self,
        *,
        bind_uuid: str,
        naga_id: str,
        delivery_signature: str,
    ) -> tuple[NagaBinding | None, bool, str]:
        async with self._lock:
            now = time.time()
            dirty = self._expire_pending_locked(now)
            dirty = self._prune_terminal_records_locked(now) or dirty

            binding = self._bindings.get(naga_id)
            if binding is not None and binding.bind_uuid == bind_uuid:
                if not secrets.compare_digest(
                    binding.delivery_signature, delivery_signature
                ):
                    if dirty:
                        await self.save()
                    return None, False, "delivery_signature 不匹配"
                if dirty:
                    await self.save()
                return _clone_binding(binding), False, ""
            if binding is not None and not binding.revoked:
                if dirty:
                    await self.save()
                return None, False, f"naga_id '{naga_id}' 已绑定"

            historical = self._history.get(bind_uuid)
            if historical is not None and historical.naga_id == naga_id:
                if not secrets.compare_digest(
                    historical.delivery_signature, delivery_signature
                ):
                    if dirty:
                        await self.save()
                    return None, False, "delivery_signature 不匹配"
                if dirty:
                    await self.save()
                return _binding_from_history(historical), False, ""

            completed = self._completed_requests.get(bind_uuid)
            if completed is not None and completed.naga_id == naga_id:
                if dirty:
                    await self.save()
                return None, False, f"bind request already {completed.status}"

            pending = self._pending.get(naga_id)
            if pending is None:
                if dirty:
                    await self.save()
                return None, False, f"naga_id '{naga_id}' 未处于待绑定状态"
            if pending.bind_uuid != bind_uuid:
                if dirty:
                    await self.save()
                return None, False, "bind_uuid 不匹配"

            binding = NagaBinding(
                naga_id=naga_id,
                bind_uuid=bind_uuid,
                delivery_signature=delivery_signature,
                qq_id=pending.qq_id,
                group_id=pending.group_id,
                created_at=now,
            )
            self._bindings[naga_id] = binding
            self._history[bind_uuid] = HistoricalBinding(
                naga_id=naga_id,
                bind_uuid=bind_uuid,
                delivery_signature=delivery_signature,
                qq_id=pending.qq_id,
                group_id=pending.group_id,
                created_at=now,
            )
            self._pending.pop(naga_id, None)
            self._completed_requests.pop(bind_uuid, None)
            await self.save()

        logger.info(
            "[NagaStore] 绑定激活: naga_id=%s qq=%d group=%d signature=%s bind_uuid=%s",
            naga_id,
            binding.qq_id,
            binding.group_id,
            mask_token(delivery_signature),
            bind_uuid,
        )
        return _clone_binding(binding), True, ""

    async def reject_binding(
        self,
        *,
        bind_uuid: str,
        naga_id: str,
        reason: str = "",
    ) -> tuple[PendingBinding | None, bool, str]:
        async with self._lock:
            now = time.time()
            dirty = self._expire_pending_locked(now)
            dirty = self._prune_terminal_records_locked(now) or dirty

            pending = self._pending.get(naga_id)
            if pending is not None and pending.bind_uuid == bind_uuid:
                removed = self._pending.pop(naga_id)
                self._completed_requests[bind_uuid] = CompletedBindRequest(
                    naga_id=removed.naga_id,
                    bind_uuid=removed.bind_uuid,
                    qq_id=removed.qq_id,
                    group_id=removed.group_id,
                    status="rejected",
                    resolved_at=now,
                    reason=reason,
                )
                await self.save()
                logger.info(
                    "[NagaStore] 绑定被远端拒绝: naga_id=%s qq=%d group=%d bind_uuid=%s",
                    naga_id,
                    removed.qq_id,
                    removed.group_id,
                    bind_uuid,
                )
                return _clone_pending(removed), True, ""

            binding = self._bindings.get(naga_id)
            if binding is not None and binding.bind_uuid == bind_uuid:
                if dirty:
                    await self.save()
                return None, False, "bind request already approved"

            completed = self._completed_requests.get(bind_uuid)
            if completed is not None and completed.naga_id == naga_id:
                if dirty:
                    await self.save()
                if completed.status == "rejected":
                    return None, False, ""
                return None, False, f"bind request already {completed.status}"

            if dirty:
                await self.save()
            return None, False, f"naga_id '{naga_id}' 未处于待绑定状态"

    async def cancel_pending(
        self,
        naga_id: str,
        *,
        bind_uuid: str | None = None,
        reason: str = "cancelled",
    ) -> PendingBinding | None:
        async with self._lock:
            pending = self._pending.get(naga_id)
            if pending is None:
                return None
            if bind_uuid is not None and pending.bind_uuid != bind_uuid:
                return None
            removed = self._pending.pop(naga_id)
            self._completed_requests[removed.bind_uuid] = CompletedBindRequest(
                naga_id=removed.naga_id,
                bind_uuid=removed.bind_uuid,
                qq_id=removed.qq_id,
                group_id=removed.group_id,
                status="cancelled",
                resolved_at=time.time(),
                reason=reason,
            )
            await self.save()
            return _clone_pending(removed)

    async def revoke_binding(
        self,
        naga_id: str,
        *,
        expected_bind_uuid: str | None = None,
        delivery_signature: str | None = None,
        wait_for_delivery: bool = True,
    ) -> tuple[NagaBinding | None, bool, str]:
        async with self._delivery_condition:
            now = time.time()
            dirty = self._expire_pending_locked(now)
            dirty = self._prune_terminal_records_locked(now) or dirty

            def _historical_match() -> NagaBinding | None:
                if not expected_bind_uuid:
                    return None
                historical = self._history.get(expected_bind_uuid)
                if historical is None or historical.naga_id != naga_id:
                    return None
                if delivery_signature is not None and not secrets.compare_digest(
                    historical.delivery_signature, delivery_signature
                ):
                    return None
                return _binding_from_history(historical)

            current = self._bindings.get(naga_id)
            if current is None:
                historical_binding = _historical_match()
                if dirty:
                    await self.save()
                if historical_binding is not None and historical_binding.revoked:
                    return historical_binding, False, ""
                return None, False, "binding not found"

            if (
                expected_bind_uuid is not None
                and current.bind_uuid != expected_bind_uuid
            ):
                historical_binding = _historical_match()
                if dirty:
                    await self.save()
                if historical_binding is not None and historical_binding.revoked:
                    return historical_binding, False, ""
                if historical_binding is not None:
                    return None, False, "binding generation is not current"
                return None, False, "bind_uuid 不匹配"

            if delivery_signature is not None and not secrets.compare_digest(
                current.delivery_signature, delivery_signature
            ):
                if dirty:
                    await self.save()
                return None, False, "delivery_signature 不匹配"

            changed = False
            if not current.revoked:
                current.revoked = True
                current.revoked_at = now
                historical = self._history.get(current.bind_uuid)
                if historical is not None:
                    historical.revoked = True
                    historical.revoked_at = now
                changed = True
                await self.save()
            elif dirty:
                await self.save()

            if wait_for_delivery:
                while self._active_deliveries.get(current.bind_uuid, 0) > 0:
                    await self._delivery_condition.wait()

            logger.info(
                "[NagaStore] 绑定已吊销: naga_id=%s bind_uuid=%s changed=%s",
                naga_id,
                current.bind_uuid,
                changed,
            )
            return _clone_binding(current), changed, ""

    async def revoke(self, naga_id: str) -> bool:
        binding, changed, _ = await self.revoke_binding(naga_id)
        return binding is not None and changed

    async def acquire_delivery(
        self, *, naga_id: str, bind_uuid: str, delivery_signature: str
    ) -> tuple[NagaBinding | None, str]:
        async with self._lock:
            binding = self._bindings.get(naga_id)
            if binding is None:
                return None, f"naga_id '{naga_id}' 未绑定"
            if binding.revoked:
                return None, f"naga_id '{naga_id}' 绑定已吊销"
            if binding.bind_uuid != bind_uuid:
                return None, "bind_uuid 不匹配"
            if not secrets.compare_digest(
                binding.delivery_signature, delivery_signature
            ):
                return None, "delivery_signature 不匹配"
            self._active_deliveries[bind_uuid] = (
                self._active_deliveries.get(bind_uuid, 0) + 1
            )
            return _clone_binding(binding), ""

    async def ensure_delivery_active(
        self, *, naga_id: str, bind_uuid: str
    ) -> tuple[NagaBinding | None, str]:
        async with self._lock:
            binding = self._bindings.get(naga_id)
            if binding is None:
                return None, f"naga_id '{naga_id}' 未绑定"
            if binding.bind_uuid != bind_uuid:
                return None, "binding generation changed"
            if binding.revoked:
                return None, f"naga_id '{naga_id}' 绑定已吊销"
            return _clone_binding(binding), ""

    async def release_delivery(self, *, bind_uuid: str) -> None:
        async with self._delivery_condition:
            count = self._active_deliveries.get(bind_uuid, 0)
            if count <= 1:
                self._active_deliveries.pop(bind_uuid, None)
                self._delivery_condition.notify_all()
                return
            self._active_deliveries[bind_uuid] = count - 1
            self._delivery_condition.notify_all()

    def list_bindings(self) -> list[NagaBinding]:
        return [_clone_binding(b) for b in self._bindings.values() if not b.revoked]

    def list_pending(self) -> list[PendingBinding]:
        return [_clone_pending(p) for p in self._pending.values()]

    def get_binding(self, naga_id: str) -> NagaBinding | None:
        binding = self._bindings.get(naga_id)
        return _clone_binding(binding) if binding is not None else None

    def get_pending(self, naga_id: str) -> PendingBinding | None:
        pending = self._pending.get(naga_id)
        return _clone_pending(pending) if pending is not None else None

    def get_binding_history(self, bind_uuid: str) -> HistoricalBinding | None:
        history = self._history.get(bind_uuid)
        return _clone_history(history) if history is not None else None

    def verify_delivery(
        self, *, naga_id: str, bind_uuid: str, delivery_signature: str
    ) -> tuple[NagaBinding | None, str]:
        binding = self._bindings.get(naga_id)
        if binding is None:
            return None, f"naga_id '{naga_id}' 未绑定"
        if binding.revoked:
            return None, f"naga_id '{naga_id}' 绑定已吊销"
        if binding.bind_uuid != bind_uuid:
            return None, "bind_uuid 不匹配"
        if not secrets.compare_digest(binding.delivery_signature, delivery_signature):
            return None, "delivery_signature 不匹配"
        return _clone_binding(binding), ""

    async def record_usage(self, naga_id: str, *, bind_uuid: str) -> None:
        async with self._lock:
            now = time.time()
            dirty = False

            historical = self._history.get(bind_uuid)
            if historical is not None and historical.naga_id == naga_id:
                historical.last_used_at = now
                historical.use_count += 1
                dirty = True

            binding = self._bindings.get(naga_id)
            if binding is not None and binding.bind_uuid == bind_uuid:
                binding.last_used_at = now
                binding.use_count += 1
                dirty = True

            if dirty:
                await self.save()
