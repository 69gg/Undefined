from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import aiofiles

logger = logging.getLogger(__name__)


async def execute(args: dict[str, Any], context: dict[str, Any]) -> str:
    """读取工作区内文件的文本内容。"""

    rel_path = str(args.get("path", "")).strip()
    max_chars: int | None = args.get("max_chars")

    if not rel_path:
        return "错误：path 不能为空"

    workspace: Path | None = context.get("workspace")
    if not workspace:
        return "错误：workspace 未设置"

    full_path = (workspace / rel_path).resolve()
    if not str(full_path).startswith(str(workspace.resolve())):
        return "错误：路径越界，只能读取 /workspace 下的文件"

    if not full_path.exists():
        return f"文件不存在: {rel_path}"
    if full_path.is_dir():
        return f"错误：{rel_path} 是目录，不是文件"

    try:
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
        return f"读取文件失败: {exc}"
