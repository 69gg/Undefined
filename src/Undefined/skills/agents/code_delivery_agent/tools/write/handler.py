from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import aiofiles

logger = logging.getLogger(__name__)


async def execute(args: dict[str, Any], context: dict[str, Any]) -> str:
    """写入文件到工作区。"""

    rel_path = str(args.get("path", "")).strip()
    content = str(args.get("content", ""))
    mode = str(args.get("mode", "overwrite")).strip().lower()

    if not rel_path:
        return "错误：path 不能为空"

    workspace: Path | None = context.get("workspace")
    if not workspace:
        return "错误：workspace 未设置"

    full_path = (workspace / rel_path).resolve()
    if not str(full_path).startswith(str(workspace.resolve())):
        return "错误：路径越界，只能写入 /workspace 下的文件"

    try:
        full_path.parent.mkdir(parents=True, exist_ok=True)

        if mode == "append":
            async with aiofiles.open(full_path, "a", encoding="utf-8") as f:
                await f.write(content)
        else:
            async with aiofiles.open(full_path, "w", encoding="utf-8") as f:
                await f.write(content)

        byte_count = len(content.encode("utf-8"))
        action = "追加" if mode == "append" else "写入"
        return f"已{action} {byte_count} 字节到 {rel_path}"
    except Exception as exc:
        logger.exception("写入文件失败: %s", rel_path)
        return f"写入文件失败: {exc}"
