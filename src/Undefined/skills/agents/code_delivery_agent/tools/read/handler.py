from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

import aiofiles

logger = logging.getLogger(__name__)


async def _read_single_file(
    rel_path: str,
    workspace: Path,
    mode: str,
    max_chars: int | None,
    offset: int | None,
    limit: int | None,
) -> str:
    """读取单个文件。"""
    full_path = (workspace / rel_path).resolve()
    if not str(full_path).startswith(str(workspace.resolve())):
        return f"错误：路径越界: {rel_path}"

    if not full_path.exists():
        return f"文件不存在: {rel_path}"
    if full_path.is_dir():
        return f"错误：{rel_path} 是目录，不是文件"

    try:
        if mode == "stat":
            stat = full_path.stat()
            size_bytes = stat.st_size
            mtime = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")

            # 计算行数
            line_count = 0
            async with aiofiles.open(
                full_path, "r", encoding="utf-8", errors="replace"
            ) as f:
                async for _ in f:
                    line_count += 1

            return (
                f"文件: {rel_path}\n"
                f"大小: {size_bytes} 字节 ({size_bytes / 1024:.2f} KB)\n"
                f"修改时间: {mtime}\n"
                f"行数: {line_count}"
            )

        elif mode == "lines":
            if offset is None:
                offset = 1
            if limit is None:
                limit = 100

            async with aiofiles.open(
                full_path, "r", encoding="utf-8", errors="replace"
            ) as f:
                lines = await f.readlines()

            total_lines = len(lines)
            start_idx = max(0, offset - 1)
            end_idx = min(total_lines, start_idx + limit)

            if start_idx >= total_lines:
                return (
                    f"{rel_path}: 起始行号 {offset} 超出文件范围（共 {total_lines} 行）"
                )

            selected_lines = lines[start_idx:end_idx]
            content = "".join(selected_lines)

            header = f"=== {rel_path} (行 {offset}-{start_idx + len(selected_lines)}/{total_lines}) ===\n"
            return header + content

        else:  # full mode
            async with aiofiles.open(
                full_path, "r", encoding="utf-8", errors="replace"
            ) as f:
                content = await f.read()

            total = len(content)
            if max_chars and total > max_chars:
                content = content[:max_chars]
                content += f"\n\n... (共 {total} 字符，已截断到前 {max_chars} 字符)"

            return content

    except Exception as exc:
        logger.exception("读取文件失败: %s", rel_path)
        return f"读取文件失败 {rel_path}: {exc}"


async def execute(args: dict[str, Any], context: dict[str, Any]) -> str:
    """读取工作区内文件的文本内容。支持多种读取模式。"""

    path_arg = str(args.get("path", "")).strip()
    mode = str(args.get("mode", "full")).strip().lower()
    max_chars: int | None = args.get("max_chars")
    offset: int | None = args.get("offset")
    limit: int | None = args.get("limit")

    if not path_arg:
        return "错误：path 不能为空"

    workspace: Path | None = context.get("workspace")
    if not workspace:
        return "错误：workspace 未设置"

    # 支持批量读取（逗号分隔）
    paths = [p.strip() for p in path_arg.split(",") if p.strip()]

    if len(paths) == 1:
        return await _read_single_file(
            paths[0], workspace, mode, max_chars, offset, limit
        )

    # 批量读取
    results: list[str] = []
    for rel_path in paths:
        result = await _read_single_file(
            rel_path, workspace, mode, max_chars, offset, limit
        )
        results.append(f"=== {rel_path} ===\n{result}\n")

    return "\n".join(results)
