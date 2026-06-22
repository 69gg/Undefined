"""合并转发节点快照缓存。

OneBot 协议端可能只允许在收到外层合并转发时读取内层内容；之后再用
内层 ID 调 ``get_forward_msg`` 可能返回空。这里按会话作用域保存已见节点，
供 ``messages.get_forward_msg`` 在协议端不可回源时回退。
"""

from __future__ import annotations

from datetime import datetime
import hashlib
from pathlib import Path
from typing import Any, Mapping

from Undefined.utils import io
from Undefined.utils.paths import FORWARD_SNAPSHOT_CACHE_DIR


def _snapshot_key(scope_key: str, forward_id: str) -> str:
    payload = f"{scope_key}\n{forward_id}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _snapshot_path(scope_key: str, forward_id: str) -> Path:
    return FORWARD_SNAPSHOT_CACHE_DIR / f"{_snapshot_key(scope_key, forward_id)}.json"


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
