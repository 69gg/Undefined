from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


async def execute(args: dict[str, Any], context: dict[str, Any]) -> str:
    """安全删除文件或目录。"""

    rel_path = str(args.get("path", "")).strip()
    recursive = bool(args.get("recursive", False))

    if not rel_path:
        return "错误：path 不能为空"

    workspace: Path | None = context.get("workspace")
    if not workspace:
        return "错误：workspace 未设置"

    full_path = (workspace / rel_path).resolve()
    if not str(full_path).startswith(str(workspace.resolve())):
        return "错误：路径越界，只能删除 /workspace 下的文件"

    # 额外安全检查：不允许删除 workspace 根目录
    if full_path == workspace.resolve():
        return "错误：不能删除 workspace 根目录"

    if not full_path.exists():
        return f"路径不存在: {rel_path}"

    try:
        if full_path.is_dir():
            # 检查是否为空目录
            try:
                entries = list(full_path.iterdir())
                is_empty = len(entries) == 0
            except Exception:
                is_empty = False

            if not is_empty and not recursive:
                return f"错误：{rel_path} 是非空目录，需要设置 recursive=true"

            # 递归删除目录
            shutil.rmtree(full_path)
            return f"已删除目录: {rel_path} (递归)"
        else:
            # 删除文件
            full_path.unlink()
            return f"已删除文件: {rel_path}"

    except Exception as exc:
        logger.exception("删除失败: %s", rel_path)
        return f"删除失败: {exc}"
