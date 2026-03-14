"""Naga 绑定存储 — scoped token 管理"""

from __future__ import annotations

import asyncio
import logging
import os
import secrets
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from Undefined.utils.io import read_json, write_json

logger = logging.getLogger(__name__)

_TOKEN_PREFIX = "udf_"
_TOKEN_HEX_BYTES = 24  # 48 hex chars
_STORE_VERSION = 1
_DATA_FILE = Path("data/naga_bindings.json")


@dataclass
class NagaBinding:
    """已通过的 Naga 绑定"""

    naga_id: str
    token: str
    qq_id: int
    group_id: int
    created_at: float
    revoked: bool = False
    description: str = ""
    last_used_at: float | None = None
    use_count: int = 0


@dataclass
class PendingBinding:
    """待审核的绑定申请"""

    naga_id: str
    qq_id: int
    group_id: int
    requested_at: float


def _generate_token() -> str:
    return f"{_TOKEN_PREFIX}{secrets.token_hex(_TOKEN_HEX_BYTES)}"


def mask_token(token: str) -> str:
    """日志脱敏：只显示前 12 字符 + '...'"""
    if len(token) <= 12:
        return token
    return token[:12] + "..."


class NagaStore:
    """Naga 绑定数据管理

    内存缓存 + JSON 文件持久化，所有读操作 O(1)。
    """

    def __init__(self, data_file: Path = _DATA_FILE) -> None:
        self._data_file = data_file
        self._bindings: dict[str, NagaBinding] = {}
        self._pending: dict[str, PendingBinding] = {}
        self._lock = asyncio.Lock()

    async def load(self) -> None:
        """从文件加载绑定数据"""
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
                if isinstance(data, dict):
                    self._bindings[naga_id] = NagaBinding(
                        naga_id=str(data.get("naga_id", naga_id)),
                        token=str(data.get("token", "")),
                        qq_id=int(data.get("qq_id", 0)),
                        group_id=int(data.get("group_id", 0)),
                        created_at=float(data.get("created_at", 0)),
                        revoked=bool(data.get("revoked", False)),
                        description=str(data.get("description", "")),
                        last_used_at=data.get("last_used_at"),
                        use_count=int(data.get("use_count", 0)),
                    )

        pending_raw = raw.get("pending", {})
        if isinstance(pending_raw, dict):
            for naga_id, data in pending_raw.items():
                if isinstance(data, dict):
                    self._pending[naga_id] = PendingBinding(
                        naga_id=str(data.get("naga_id", naga_id)),
                        qq_id=int(data.get("qq_id", 0)),
                        group_id=int(data.get("group_id", 0)),
                        requested_at=float(data.get("requested_at", 0)),
                    )

        logger.info(
            "[NagaStore] 加载完成: bindings=%d pending=%d",
            len(self._bindings),
            len(self._pending),
        )

        await asyncio.to_thread(self._restrict_permissions)

    def _restrict_permissions(self) -> None:
        """限制数据文件权限（仅 Unix 生效）"""
        if os.name != "posix":
            return
        try:
            if self._data_file.exists():
                os.chmod(self._data_file, 0o600)
        except OSError as exc:
            logger.debug("[NagaStore] chmod 600 失败: %s", exc)

    async def save(self) -> None:
        """持久化到文件"""
        payload: dict[str, Any] = {
            "version": _STORE_VERSION,
            "bindings": {k: asdict(v) for k, v in self._bindings.items()},
            "pending": {k: asdict(v) for k, v in self._pending.items()},
        }
        await write_json(self._data_file, payload)
        await asyncio.to_thread(self._restrict_permissions)

    async def submit_binding(
        self, naga_id: str, qq_id: int, group_id: int
    ) -> tuple[bool, str]:
        """提交绑定申请

        Returns:
            (success, message)
        """
        async with self._lock:
            if naga_id in self._bindings:
                binding = self._bindings[naga_id]
                if not binding.revoked:
                    return False, f"naga_id '{naga_id}' 已绑定"
            if naga_id in self._pending:
                return False, f"naga_id '{naga_id}' 已在审核队列中"

            self._pending[naga_id] = PendingBinding(
                naga_id=naga_id,
                qq_id=qq_id,
                group_id=group_id,
                requested_at=time.time(),
            )
            await self.save()
        return True, "申请已提交，等待超管审核"

    async def approve(self, naga_id: str) -> NagaBinding | None:
        """审批通过：生成 token，移入 bindings"""
        async with self._lock:
            pending = self._pending.pop(naga_id, None)
            if pending is None:
                return None

            token = _generate_token()
            binding = NagaBinding(
                naga_id=naga_id,
                token=token,
                qq_id=pending.qq_id,
                group_id=pending.group_id,
                created_at=time.time(),
            )
            self._bindings[naga_id] = binding
            await self.save()
        logger.info(
            "[NagaStore] 绑定审批通过: naga_id=%s qq=%d group=%d token=%s",
            naga_id,
            binding.qq_id,
            binding.group_id,
            mask_token(token),
        )
        return binding

    async def reject(self, naga_id: str) -> bool:
        """拒绝绑定申请"""
        async with self._lock:
            if naga_id not in self._pending:
                return False
            del self._pending[naga_id]
            await self.save()
        logger.info("[NagaStore] 绑定申请已拒绝: naga_id=%s", naga_id)
        return True

    async def revoke(self, naga_id: str) -> bool:
        """吊销已有绑定"""
        async with self._lock:
            binding = self._bindings.get(naga_id)
            if binding is None or binding.revoked:
                return False
            binding.revoked = True
            await self.save()
        logger.info("[NagaStore] 绑定已吊销: naga_id=%s", naga_id)
        return True

    def list_bindings(self) -> list[NagaBinding]:
        """列出所有活跃绑定"""
        return [b for b in self._bindings.values() if not b.revoked]

    def list_pending(self) -> list[PendingBinding]:
        """列出所有待审核申请"""
        return list(self._pending.values())

    def get_binding(self, naga_id: str) -> NagaBinding | None:
        """按 naga_id 查询绑定"""
        return self._bindings.get(naga_id)

    def verify(self, naga_id: str, token: str) -> tuple[bool, str]:
        """校验 scoped token（纯内存操作）

        Returns:
            (valid, error_message)
        """
        binding = self._bindings.get(naga_id)
        if binding is None:
            return False, f"naga_id '{naga_id}' 未绑定"
        if binding.revoked:
            return False, f"naga_id '{naga_id}' 绑定已吊销"
        if not secrets.compare_digest(binding.token, token):
            return False, "token 不匹配"
        return True, ""

    async def record_usage(self, naga_id: str) -> None:
        """更新使用记录"""
        async with self._lock:
            binding = self._bindings.get(naga_id)
            if binding is None:
                return
            binding.last_used_at = time.time()
            binding.use_count += 1
            await self.save()
