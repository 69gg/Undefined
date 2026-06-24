"""合并转发节点快照缓存。

OneBot 协议端可能只允许在收到外层合并转发时读取内层内容；之后再用
内层 ID 调 ``get_forward_msg`` 可能返回空。这里按会话作用域保存已见节点，
供 ``messages.get_forward_msg`` 在协议端不可回源时回退。
"""

from __future__ import annotations

import asyncio
from datetime import datetime
import hashlib
import logging
from pathlib import Path
from typing import Any, Awaitable, Callable, Mapping

from Undefined.utils import io
from Undefined.utils.paths import FORWARD_SNAPSHOT_CACHE_DIR

logger = logging.getLogger(__name__)

_MAX_RECURSIVE_SNAPSHOT_DEPTH = 3
_MAX_RECURSIVE_SNAPSHOT_NODES = 50
_snapshot_locks: dict[str, asyncio.Lock] = {}
_snapshot_lock_users: dict[str, int] = {}
_snapshot_inflight: dict[str, asyncio.Task[None]] = {}


def _snapshot_key(scope_key: str, forward_id: str) -> str:
    payload = f"{scope_key}\n{forward_id}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _snapshot_path(scope_key: str, forward_id: str) -> Path:
    return FORWARD_SNAPSHOT_CACHE_DIR / f"{_snapshot_key(scope_key, forward_id)}.json"


def _snapshot_lock(scope_key: str, forward_id: str) -> tuple[str, asyncio.Lock]:
    key = _snapshot_key(scope_key, forward_id)
    lock = _snapshot_locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _snapshot_locks[key] = lock
    _snapshot_lock_users[key] = _snapshot_lock_users.get(key, 0) + 1
    return key, lock


def _release_snapshot_lock(key: str, lock: asyncio.Lock) -> None:
    users = _snapshot_lock_users.get(key, 0) - 1
    if users > 0:
        _snapshot_lock_users[key] = users
        return
    _snapshot_lock_users.pop(key, None)
    if _snapshot_locks.get(key) is lock and not lock.locked():
        _snapshot_locks.pop(key, None)


def _clean_json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        cleaned: dict[str, Any] = {}
        for raw_key, raw_value in value.items():
            key = str(raw_key).strip()
            if not key:
                continue
            cleaned[key] = _clean_json_value(raw_value)
        return cleaned
    if isinstance(value, (list, tuple)):
        return [_clean_json_value(item) for item in value]
    return str(value)


def normalize_forward_nodes_for_snapshot(nodes: Any) -> list[dict[str, Any]]:
    """把 OneBot 返回的合并转发节点清洗为可持久化列表。"""
    if isinstance(nodes, Mapping):
        messages = nodes.get("messages")
        raw_nodes = messages if isinstance(messages, list) else []
    elif isinstance(nodes, list):
        raw_nodes = nodes
    else:
        raw_nodes = []

    cleaned_nodes: list[dict[str, Any]] = []
    for node in raw_nodes:
        if not isinstance(node, Mapping):
            continue
        cleaned = _clean_json_value(node)
        if isinstance(cleaned, dict):
            cleaned_nodes.append(cleaned)
    return cleaned_nodes


async def save_forward_snapshot(
    *,
    scope_key: str,
    forward_id: str,
    nodes: Any,
) -> bool:
    """保存合并转发节点快照；无有效节点时不写入。"""
    normalized_scope = str(scope_key or "").strip()
    normalized_forward_id = str(forward_id or "").strip()
    if not normalized_scope or not normalized_forward_id:
        return False

    normalized_nodes = normalize_forward_nodes_for_snapshot(nodes)
    if not normalized_nodes:
        return False

    payload = {
        "scope_key": normalized_scope,
        "forward_id": normalized_forward_id,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "nodes": normalized_nodes,
    }
    await io.write_json(
        _snapshot_path(normalized_scope, normalized_forward_id),
        payload,
        use_lock=True,
    )
    return True


async def load_forward_snapshot(
    *,
    scope_key: str,
    forward_id: str,
) -> list[dict[str, Any]]:
    """读取合并转发节点快照；不存在或格式不符时返回空列表。"""
    normalized_scope = str(scope_key or "").strip()
    normalized_forward_id = str(forward_id or "").strip()
    if not normalized_scope or not normalized_forward_id:
        return []

    raw = await io.read_json(
        _snapshot_path(normalized_scope, normalized_forward_id),
        use_lock=False,
    )
    if not isinstance(raw, Mapping):
        return []
    if str(raw.get("scope_key", "") or "") != normalized_scope:
        return []
    if str(raw.get("forward_id", "") or "") != normalized_forward_id:
        return []
    return normalize_forward_nodes_for_snapshot(raw.get("nodes"))


def _extract_forward_id(data: Mapping[str, Any]) -> str:
    forward_id = data.get("id") or data.get("resid") or data.get("message_id")
    return str(forward_id).strip() if forward_id is not None else ""


def _normalize_message_segments(message: Any) -> list[Mapping[str, Any]]:
    if isinstance(message, list):
        return [item for item in message if isinstance(item, Mapping)]
    if isinstance(message, Mapping):
        return [message]
    if isinstance(message, str):
        return [{"type": "text", "data": {"text": message}}]
    return []


def _iter_nested_forward_ids(nodes: list[dict[str, Any]]) -> list[str]:
    forward_ids: list[str] = []
    seen: set[str] = set()
    for node in nodes:
        raw_message = (
            node.get("content") or node.get("message") or node.get("raw_message")
        )
        for segment in _normalize_message_segments(raw_message):
            if str(segment.get("type", "") or "").strip().lower() != "forward":
                continue
            raw_data = segment.get("data", {})
            data = raw_data if isinstance(raw_data, Mapping) else {}
            forward_id = _extract_forward_id(data)
            if forward_id and forward_id not in seen:
                seen.add(forward_id)
                forward_ids.append(forward_id)
    return forward_ids


async def snapshot_forward_tree(
    *,
    scope_key: str,
    forward_id: str,
    get_forward_messages: Callable[[str], Awaitable[Any]],
    max_depth: int = _MAX_RECURSIVE_SNAPSHOT_DEPTH,
    max_nodes: int = _MAX_RECURSIVE_SNAPSHOT_NODES,
) -> None:
    """递归抓取并保存当前可访问的合并转发树。

    同一 ``scope_key + forward_id`` 在进程内会合并并发抓取，避免多个消息或
    工具调用同时触发同一层 OneBot 请求。
    """
    normalized_scope = str(scope_key or "").strip()
    normalized_forward_id = str(forward_id or "").strip()
    if not normalized_scope or not normalized_forward_id:
        return
    if max_depth < 0 or max_nodes <= 0:
        return

    root_key = _snapshot_key(normalized_scope, normalized_forward_id)
    inflight = _snapshot_inflight.get(root_key)
    if inflight is not None and not inflight.done():
        await asyncio.shield(inflight)
        return

    async def _run() -> None:
        visited: set[str] = set()
        remaining = max_nodes

        async def _walk(current_forward_id: str, depth: int) -> None:
            nonlocal remaining
            normalized_current_id = str(current_forward_id or "").strip()
            if not normalized_current_id:
                return
            if depth > max_depth or remaining <= 0:
                return
            if normalized_current_id in visited:
                return
            visited.add(normalized_current_id)
            remaining -= 1

            lock_key, lock = _snapshot_lock(normalized_scope, normalized_current_id)
            try:
                async with lock:
                    nodes: list[dict[str, Any]] = []
                    try:
                        nodes = await load_forward_snapshot(
                            scope_key=normalized_scope,
                            forward_id=normalized_current_id,
                        )
                    except Exception:
                        logger.debug(
                            "读取合并转发快照失败，将尝试回源: id=%s",
                            normalized_current_id,
                            exc_info=True,
                        )
                    if not nodes:
                        try:
                            raw_nodes = await get_forward_messages(
                                normalized_current_id
                            )
                        except Exception:
                            logger.debug(
                                "递归缓存合并转发失败: id=%s",
                                normalized_current_id,
                                exc_info=True,
                            )
                            return
                        nodes = normalize_forward_nodes_for_snapshot(raw_nodes)
                    if not nodes:
                        return
                    try:
                        await save_forward_snapshot(
                            scope_key=normalized_scope,
                            forward_id=normalized_current_id,
                            nodes=nodes,
                        )
                    except Exception:
                        logger.debug(
                            "写入合并转发快照失败: id=%s",
                            normalized_current_id,
                            exc_info=True,
                        )
            finally:
                _release_snapshot_lock(lock_key, lock)

            if depth >= max_depth:
                return
            for nested_forward_id in _iter_nested_forward_ids(nodes):
                if remaining <= 0:
                    break
                await _walk(nested_forward_id, depth + 1)

        await _walk(normalized_forward_id, 0)

    task = asyncio.create_task(_run())
    _snapshot_inflight[root_key] = task

    def _forget(done: asyncio.Task[None]) -> None:
        if _snapshot_inflight.get(root_key) is done:
            _snapshot_inflight.pop(root_key, None)

    task.add_done_callback(_forget)
    await asyncio.shield(task)
