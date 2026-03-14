"""Naga 绑定存储。"""

from __future__ import annotations

import asyncio
import logging
import os
import secrets
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from uuid import uuid4
from typing import Any

from Undefined.utils.io import read_json, write_json

logger = logging.getLogger(__name__)

_STORE_VERSION = 2
_DATA_FILE = Path("data/naga_bindings.json")


@dataclass
class NagaBinding:
    """已激活的 Naga 绑定。"""

    naga_id: str
    bind_uuid: str
    delivery_signature: str
    qq_id: int
    group_id: int
    created_at: float
    revoked: bool = False
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


def generate_bind_uuid() -> str:
    return uuid4().hex


def mask_token(token: str) -> str:
    """日志脱敏：只显示前 12 字符 + '...'。"""
    if len(token) <= 12:
        return token
    return token[:12] + "..."


class NagaStore:
    """Naga 绑定数据管理。"""

    def __init__(self, data_file: Path = _DATA_FILE) -> None:
        self._data_file = data_file
        self._bindings: dict[str, NagaBinding] = {}
        self._pending: dict[str, PendingBinding] = {}
        self._lock = asyncio.Lock()

    async def load(self) -> None:
        raw = await read_json(self._data_file, use_lock=True)
        if raw is None:
            logger.info("[NagaStore] 绑定文件不存在，使用空数据")
            return
        if not isinstance(raw, dict):
            logger.warning("[NagaStore] 绑定文件格式错误，使用空数据")
            return

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
                )

        logger.info(
            "[NagaStore] 加载完成: bindings=%d pending=%d",
            len(self._bindings),
            len(self._pending),
        )
        await asyncio.to_thread(self._restrict_permissions)

    def _restrict_permissions(self) -> None:
        if os.name != "posix":
            return
        try:
            if self._data_file.exists():
                os.chmod(self._data_file, 0o600)
        except OSError as exc:
            logger.debug("[NagaStore] chmod 600 失败: %s", exc)

    async def save(self) -> None:
        payload: dict[str, Any] = {
            "version": _STORE_VERSION,
            "bindings": {k: asdict(v) for k, v in self._bindings.items()},
            "pending": {k: asdict(v) for k, v in self._pending.items()},
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
            active = self._bindings.get(naga_id)
            if active is not None and not active.revoked:
                return False, f"naga_id '{naga_id}' 已绑定", None
            if naga_id in self._pending:
                return False, f"naga_id '{naga_id}' 已在处理中", None

            pending = PendingBinding(
                naga_id=naga_id,
                bind_uuid=str(bind_uuid or generate_bind_uuid()),
                qq_id=qq_id,
                group_id=group_id,
                requested_at=time.time(),
                request_context=dict(request_context or {}),
            )
            self._pending[naga_id] = pending
            await self.save()
        return True, "申请已提交，等待 Naga 端确认", pending

    async def activate_binding(
        self,
        *,
        bind_uuid: str,
        naga_id: str,
        delivery_signature: str,
    ) -> tuple[NagaBinding | None, bool, str]:
        async with self._lock:
            binding = self._bindings.get(naga_id)
            if binding is not None and not binding.revoked:
                if binding.bind_uuid == bind_uuid and secrets.compare_digest(
                    binding.delivery_signature, delivery_signature
                ):
                    return binding, False, ""
                return None, False, f"naga_id '{naga_id}' 已绑定"

            pending = self._pending.get(naga_id)
            if pending is None:
                return None, False, f"naga_id '{naga_id}' 未处于待绑定状态"
            if pending.bind_uuid != bind_uuid:
                return None, False, "bind_uuid 不匹配"

            binding = NagaBinding(
                naga_id=naga_id,
                bind_uuid=bind_uuid,
                delivery_signature=delivery_signature,
                qq_id=pending.qq_id,
                group_id=pending.group_id,
                created_at=time.time(),
            )
            self._bindings[naga_id] = binding
            self._pending.pop(naga_id, None)
            await self.save()

        logger.info(
            "[NagaStore] 绑定激活: naga_id=%s qq=%d group=%d signature=%s bind_uuid=%s",
            naga_id,
            binding.qq_id,
            binding.group_id,
            mask_token(delivery_signature),
            bind_uuid,
        )
        return binding, True, ""

    async def reject_binding(
        self, *, bind_uuid: str, naga_id: str
    ) -> tuple[PendingBinding | None, bool, str]:
        async with self._lock:
            pending = self._pending.get(naga_id)
            if pending is None:
                return None, False, f"naga_id '{naga_id}' 未处于待绑定状态"
            if pending.bind_uuid != bind_uuid:
                return None, False, "bind_uuid 不匹配"
            removed = self._pending.pop(naga_id)
            await self.save()
        logger.info(
            "[NagaStore] 绑定被远端拒绝: naga_id=%s qq=%d group=%d bind_uuid=%s",
            naga_id,
            removed.qq_id,
            removed.group_id,
            bind_uuid,
        )
        return removed, True, ""

    async def cancel_pending(
        self, naga_id: str, *, bind_uuid: str | None = None
    ) -> PendingBinding | None:
        async with self._lock:
            pending = self._pending.get(naga_id)
            if pending is None:
                return None
            if bind_uuid is not None and pending.bind_uuid != bind_uuid:
                return None
            removed = self._pending.pop(naga_id)
            await self.save()
            return removed

    async def revoke(self, naga_id: str) -> bool:
        async with self._lock:
            binding = self._bindings.get(naga_id)
            if binding is None or binding.revoked:
                return False
            binding.revoked = True
            await self.save()
        logger.info("[NagaStore] 绑定已吊销: naga_id=%s", naga_id)
        return True

    def list_bindings(self) -> list[NagaBinding]:
        return [b for b in self._bindings.values() if not b.revoked]

    def list_pending(self) -> list[PendingBinding]:
        return list(self._pending.values())

    def get_binding(self, naga_id: str) -> NagaBinding | None:
        return self._bindings.get(naga_id)

    def get_pending(self, naga_id: str) -> PendingBinding | None:
        return self._pending.get(naga_id)

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
        return binding, ""

    async def record_usage(self, naga_id: str) -> None:
        async with self._lock:
            binding = self._bindings.get(naga_id)
            if binding is None:
                return
            binding.last_used_at = time.time()
            binding.use_count += 1
            await self.save()
