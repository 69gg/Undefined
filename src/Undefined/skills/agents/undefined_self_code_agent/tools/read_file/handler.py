from __future__ import annotations

import asyncio
import logging
from typing import Any

from Undefined.skills.agents.undefined_self_code_agent.tools._shared import (
    DEFAULT_LINE_LIMIT,
    DEFAULT_MAX_CHARS,
    allowed_roots_text,
    clamp_int,
    path_exists,
    path_is_file,
    read_text_file,
    resolve_allowed_path,
)

logger = logging.getLogger(__name__)


async def execute(args: dict[str, Any], context: dict[str, Any]) -> str:
    """读取允许范围内的文本文件。"""

    file_path = str(args.get("file_path") or args.get("path") or "").strip()
    if not file_path:
        return "错误：file_path 不能为空"

    try:
        resolved = resolve_allowed_path(file_path, context)
    except PermissionError as exc:
        return f"权限不足：{exc}。{allowed_roots_text()}"
    except ValueError as exc:
        return f"错误：{exc}"

    if not await path_exists(resolved.path):
        return f"文件不存在: {file_path}"
    if not await path_is_file(resolved.path):
        return f"错误：{file_path} 不是文件"

    try:
        content, truncated_bytes, size = await asyncio.to_thread(
            read_text_file, resolved.path
        )
    except UnicodeError:
        return f"错误：{resolved.rel_path} 不是可读取的文本文件"
    except OSError as exc:
        logger.exception("读取文件失败: %s", resolved.rel_path)
        return f"读取文件失败 {resolved.rel_path}: {exc}"

    offset_raw = args.get("offset")
    limit_raw = args.get("limit")
    line_window = offset_raw is not None or limit_raw is not None
    header = f"=== {resolved.rel_path} ({size} bytes) ==="

    if line_window:
        lines = content.splitlines()
        total_lines = len(lines)
        offset = clamp_int(offset_raw, 1, 1, max(total_lines, 1))
        limit = clamp_int(limit_raw, DEFAULT_LINE_LIMIT, 1, 2000)
        start_idx = offset - 1
        selected = lines[start_idx : start_idx + limit]
        end_line = start_idx + len(selected)
        body = "\n".join(selected)
        if total_lines == 0 or not selected:
            range_header = f"{header}\n行 0-0/0（空文件）"
        else:
            range_header = f"{header}\n行 {offset}-{end_line}/{total_lines}"
        if truncated_bytes:
            range_header += "\n提示：文件因大小限制只读取了前一部分字节"
        return f"{range_header}\n{body}"

    max_chars = clamp_int(args.get("max_chars"), DEFAULT_MAX_CHARS, 1000, 200000)
    total_chars = len(content)
    truncated_chars = total_chars > max_chars
    if truncated_chars:
        content = content[:max_chars]

    notes: list[str] = []
    if truncated_bytes:
        notes.append("文件因大小限制只读取了前一部分字节")
    if truncated_chars:
        notes.append(f"内容共 {total_chars} 字符，已截断到前 {max_chars} 字符")
    note_text = "\n".join(f"提示：{note}" for note in notes)
    if note_text:
        return f"{header}\n{note_text}\n{content}"
    return f"{header}\n{content}"
