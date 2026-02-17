"""会话内进行中任务摘要存储（内存态，不持久化）。"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, TypedDict

import logging


logger = logging.getLogger(__name__)


class InflightTaskLocation(TypedDict):
    """进行中任务的会话位置。"""

    type: Literal["group", "private"]
    name: str
    id: int


class InflightTaskRecord(TypedDict):
    """对外暴露的进行中任务记录。"""

    request_id: str
    status: Literal["pending", "ready"]
    created_at: str
    updated_at: str
    location: InflightTaskLocation
    source_message: str
    display_text: str


@dataclass
class _InflightEntry:
    request_id: str
    status: Literal["pending", "ready"]
    created_at: str
    updated_at: str
    location: InflightTaskLocation
    source_message: str
    display_text: str
    expires_at_monotonic: float


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _format_location(location: InflightTaskLocation) -> str:
    return f"{location['type']}:{location['name']}({location['id']})"


def _format_pending_text(
    timestamp: str, location: InflightTaskLocation, source_message: str
) -> str:
    return (
        f'[{timestamp}] [{_format_location(location)}] 正在处理消息："{source_message}"'
    )


def _format_ready_text(
    timestamp: str,
    location: InflightTaskLocation,
    source_message: str,
    action_summary: str,
) -> str:
    return (
        f"[{timestamp}] [{_format_location(location)}] "
        f'正在处理消息："{source_message}"（{action_summary}）'
    )


class InflightTaskStore:
    """会话级进行中任务存储。

    - 仅内存态，进程重启即丢失
    - 每个会话（group/private + chat_id）仅保留一条最新进行中记录
    """

    def __init__(
        self, ttl_seconds: int = 900, gc_interval: int = 60, gc_threshold: int = 100
    ) -> None:
        self._ttl_seconds = max(1, int(ttl_seconds))
        self._gc_interval = max(1, int(gc_interval))
        self._gc_threshold = max(1, int(gc_threshold))
        self._lock = asyncio.Lock()
        self._entries_by_chat: dict[str, _InflightEntry] = {}
        self._chat_key_by_request: dict[str, str] = {}
        self._last_gc_time = time.monotonic()

        # 性能监控指标
        self._metrics = {
            "total_upserts": 0,
            "total_mark_ready": 0,
            "total_clears": 0,
            "total_queries": 0,
            "total_gc_runs": 0,
            "total_expired_cleaned": 0,
            "anti_duplicate_hits": 0,  # 防重复命中次数
        }

    @staticmethod
    def _chat_key(request_type: str, chat_id: int) -> str:
        return f"{request_type}:{chat_id}"

    def get_metrics(self) -> dict[str, int]:
        """获取性能监控指标（非阻塞，快照读取）。"""
        return {
            **self._metrics,
            "current_entries": len(self._entries_by_chat),
        }

    def _should_gc(self) -> bool:
        """判断是否应该触发 GC（基于时间间隔或数量阈值）。"""
        now = time.monotonic()
        time_elapsed = now - self._last_gc_time >= self._gc_interval
        threshold_reached = len(self._entries_by_chat) >= self._gc_threshold
        return time_elapsed or threshold_reached

    def _gc_locked(self) -> None:
        """执行 GC 清理过期记录（必须在锁内调用）。"""
        now = time.monotonic()
        expired_keys = [
            key
            for key, entry in self._entries_by_chat.items()
            if entry.expires_at_monotonic <= now
        ]
        for key in expired_keys:
            entry = self._entries_by_chat.pop(key, None)
            if entry is not None:
                self._chat_key_by_request.pop(entry.request_id, None)

        if expired_keys:
            self._metrics["total_expired_cleaned"] += len(expired_keys)
            logger.info(
                "[进行中摘要] GC清理 expired=%s remaining=%s",
                len(expired_keys),
                len(self._entries_by_chat),
            )

        self._metrics["total_gc_runs"] += 1
        self._last_gc_time = now

    async def _maybe_gc_locked(self) -> None:
        """根据条件决定是否触发 GC（必须在锁内调用）。"""
        if self._should_gc():
            self._gc_locked()

    def _touch_expire_locked(self, entry: _InflightEntry) -> None:
        entry.expires_at_monotonic = time.monotonic() + float(self._ttl_seconds)

    @staticmethod
    def _to_record(entry: _InflightEntry) -> InflightTaskRecord:
        location: InflightTaskLocation = {
            "type": entry.location["type"],
            "name": entry.location["name"],
            "id": entry.location["id"],
        }
        record: InflightTaskRecord = {
            "request_id": entry.request_id,
            "status": entry.status,
            "created_at": entry.created_at,
            "updated_at": entry.updated_at,
            "location": location,
            "source_message": entry.source_message,
            "display_text": entry.display_text,
        }
        return record

    async def upsert_pending(
        self,
        *,
        request_id: str,
        request_type: Literal["group", "private"],
        chat_id: int,
        location_name: str,
        source_message: str,
    ) -> InflightTaskRecord:
        """创建或覆盖会话中的进行中任务占位摘要。"""
        cleaned_request_id = request_id.strip()
        cleaned_source = source_message.strip()
        safe_source = cleaned_source if cleaned_source else "(无文本内容)"
        if len(safe_source) > 120:
            safe_source = safe_source[:117].rstrip() + "..."

        safe_name = location_name.strip() if location_name.strip() else "未知会话"
        location: InflightTaskLocation = {
            "type": request_type,
            "name": safe_name,
            "id": int(chat_id),
        }

        now_iso = _now_iso()
        entry = _InflightEntry(
            request_id=cleaned_request_id,
            status="pending",
            created_at=now_iso,
            updated_at=now_iso,
            location=location,
            source_message=safe_source,
            display_text=_format_pending_text(now_iso, location, safe_source),
            expires_at_monotonic=time.monotonic() + float(self._ttl_seconds),
        )

        chat_key = self._chat_key(request_type, int(chat_id))
        async with self._lock:
            await self._maybe_gc_locked()
            previous = self._entries_by_chat.get(chat_key)
            if previous is not None:
                self._chat_key_by_request.pop(previous.request_id, None)
                logger.debug(
                    "[进行中摘要] 覆盖会话 chat=%s old=%s new=%s",
                    chat_key,
                    previous.request_id[:8],
                    cleaned_request_id[:8],
                )
            self._entries_by_chat[chat_key] = entry
            self._chat_key_by_request[cleaned_request_id] = chat_key
            self._metrics["total_upserts"] += 1
            logger.info(
                "[进行中摘要] 创建占位 chat=%s request=%s source_len=%s",
                chat_key,
                cleaned_request_id[:8],
                len(safe_source),
            )
            return self._to_record(entry)

    async def mark_ready(self, request_id: str, action_summary: str) -> bool:
        """将进行中任务标记为摘要就绪。"""
        cleaned_request_id = request_id.strip()
        action = " ".join(action_summary.split()).strip()
        if len(action) > 80:
            action = action[:77].rstrip() + "..."
        if not action:
            action = "处理中"

        async with self._lock:
            await self._maybe_gc_locked()
            chat_key = self._chat_key_by_request.get(cleaned_request_id)
            if not chat_key:
                logger.debug(
                    "[进行中摘要] 更新失败: request不存在 id=%s",
                    cleaned_request_id[:8],
                )
                return False
            entry = self._entries_by_chat.get(chat_key)
            if entry is None or entry.request_id != cleaned_request_id:
                logger.debug(
                    "[进行中摘要] 更新失败: 会话不匹配 request=%s chat=%s",
                    cleaned_request_id[:8],
                    chat_key,
                )
                return False

            now_iso = _now_iso()
            entry.status = "ready"
            entry.updated_at = now_iso
            entry.display_text = _format_ready_text(
                now_iso,
                entry.location,
                entry.source_message,
                action,
            )
            self._touch_expire_locked(entry)
            self._metrics["total_mark_ready"] += 1
            logger.info(
                "[进行中摘要] 标记就绪 chat=%s request=%s action=%s",
                chat_key,
                cleaned_request_id[:8],
                action[:20],
            )
            return True

    async def clear_by_request(self, request_id: str) -> bool:
        """按 request_id 清除对应会话中的记录。"""
        cleaned_request_id = request_id.strip()
        async with self._lock:
            await self._maybe_gc_locked()
            chat_key = self._chat_key_by_request.pop(cleaned_request_id, None)
            if chat_key is None:
                return False
            entry = self._entries_by_chat.get(chat_key)
            if entry is None:
                return False
            if entry.request_id != cleaned_request_id:
                return False
            self._entries_by_chat.pop(chat_key, None)
            self._metrics["total_clears"] += 1
            logger.info(
                "[进行中摘要] 清理成功 request=%s chat=%s",
                cleaned_request_id[:8],
                chat_key,
            )
            return True

    async def clear_for_chat(
        self,
        *,
        request_type: Literal["group", "private"],
        chat_id: int,
        owner_request_id: str | None = None,
    ) -> bool:
        """按会话清除记录，可选校验 owner_request_id。"""
        chat_key = self._chat_key(request_type, int(chat_id))
        owner = owner_request_id.strip() if isinstance(owner_request_id, str) else ""
        async with self._lock:
            await self._maybe_gc_locked()
            entry = self._entries_by_chat.get(chat_key)
            if entry is None:
                return False
            if owner and entry.request_id != owner:
                logger.debug(
                    "[进行中摘要] 清理被拒绝 chat=%s owner=%s request=%s",
                    chat_key,
                    owner[:8],
                    entry.request_id[:8],
                )
                return False
            self._entries_by_chat.pop(chat_key, None)
            self._chat_key_by_request.pop(entry.request_id, None)
            self._metrics["total_clears"] += 1
            logger.info(
                "[进行中摘要] 清理成功 chat=%s request=%s",
                chat_key,
                entry.request_id[:8],
            )
            return True

    async def list_for_chat(
        self,
        *,
        request_type: Literal["group", "private"],
        chat_id: int,
        exclude_request_id: str | None = None,
    ) -> list[InflightTaskRecord]:
        """获取指定会话当前可见的进行中记录列表。"""
        chat_key = self._chat_key(request_type, int(chat_id))
        excluded = (
            exclude_request_id.strip() if isinstance(exclude_request_id, str) else ""
        )
        async with self._lock:
            await self._maybe_gc_locked()
            entry = self._entries_by_chat.get(chat_key)
            if entry is None:
                return []
            if excluded and entry.request_id == excluded:
                logger.debug(
                    "[进行中摘要] 查询排除 chat=%s request=%s",
                    chat_key,
                    excluded[:8],
                )
                return []
            self._touch_expire_locked(entry)
            self._metrics["total_queries"] += 1
            self._metrics["anti_duplicate_hits"] += 1
            logger.info(
                "[进行中摘要] 查询命中 chat=%s request=%s status=%s",
                chat_key,
                entry.request_id[:8],
                entry.status,
            )
            return [self._to_record(entry)]
