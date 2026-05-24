"""MessageSender 辅助函数。"""

from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from Undefined.attachments import attachment_refs_to_text


def _extract_message_id(result: object) -> int | None:
    if not isinstance(result, dict):
        return None

    message_id = result.get("message_id")
    if message_id is None:
        # OneBot 实现差异：message_id 可能在顶层或 data 子对象。
        data = result.get("data")
        if isinstance(data, dict):
            message_id = data.get("message_id")

    try:
        return int(message_id) if message_id is not None else None
    except (TypeError, ValueError):
        return None


def _format_size(size_bytes: int | None) -> str:
    if size_bytes is None or size_bytes < 0:
        return "未知大小"
    if size_bytes < 1024:
        return f"{size_bytes}B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f}KB"
    if size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / 1024 / 1024:.2f}MB"
    return f"{size_bytes / 1024 / 1024 / 1024:.2f}GB"


def _build_file_history_message(file_name: str, size_bytes: int | None) -> str:
    return f"[文件] {file_name} ({_format_size(size_bytes)})"


def _append_attachment_refs(
    history_content: str,
    attachments: list[dict[str, str]] | None,
) -> str:
    refs_text = attachment_refs_to_text(attachments or [])
    if not refs_text or refs_text in history_content:
        return history_content
    if not history_content:
        return refs_text
    return f"{history_content}\n{refs_text}"


def _merge_attachment_refs(
    *groups: list[dict[str, str]] | None,
) -> list[dict[str, str]]:
    merged: list[dict[str, str]] = []
    seen_uids: set[str] = set()
    for group in groups:
        for item in group or []:
            uid = str(item.get("uid", "") or "").strip()
            if uid and uid in seen_uids:
                continue
            if uid:
                seen_uids.add(uid)
            merged.append(item)
    return merged


def _iter_segments_deep(value: object) -> list[dict[str, Any]]:
    """递归收集消息段，用于合并转发中的本地媒体登记。"""
    segments: list[dict[str, Any]] = []
    if isinstance(value, dict):
        type_value = value.get("type")
        data = value.get("data")
        if type_value is not None and isinstance(data, dict):
            segments.append(value)
            content = data.get("content")
            if isinstance(content, (list, dict)):
                segments.extend(_iter_segments_deep(content))
        else:
            for child in value.values():
                if isinstance(child, (list, dict)):
                    segments.extend(_iter_segments_deep(child))
    elif isinstance(value, list):
        for child in value:
            if isinstance(child, (list, dict)):
                segments.extend(_iter_segments_deep(child))
    return segments


def _local_path_from_segment_source(source: Any) -> Path | None:
    raw_source = str(source or "").strip()
    if not raw_source:
        return None
    lowered = raw_source.lower()
    if lowered.startswith(("http://", "https://", "base64://")):
        return None
    if lowered.startswith("file://"):
        parsed = urlsplit(raw_source)
        path = Path(unquote(parsed.path)).expanduser()
    else:
        path = Path(raw_source).expanduser()
    if not path.is_absolute():
        path = (Path.cwd() / path).resolve()
    else:
        path = path.resolve()
    return path if path.is_file() else None


def _get_file_size(file_path: str) -> int | None:
    try:
        return Path(file_path).stat().st_size
    except OSError:
        return None
