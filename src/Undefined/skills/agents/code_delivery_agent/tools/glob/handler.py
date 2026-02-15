from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

MAX_RESULTS = 500


async def execute(args: dict[str, Any], context: dict[str, Any]) -> str:
    """按 glob 模式匹配工作区内的文件。"""

    pattern = str(args.get("pattern", "")).strip()
    base_path_rel = str(args.get("base_path", "")).strip()

    if not pattern:
        return "错误：pattern 不能为空"

    workspace: Path | None = context.get("workspace")
    if not workspace:
        return "错误：workspace 未设置"

    ws_resolved = workspace.resolve()

    if base_path_rel:
        search_root = (workspace / base_path_rel).resolve()
        if not str(search_root).startswith(str(ws_resolved)):
            return "错误：base_path 越界"
        if not search_root.is_dir():
            return f"错误：base_path 不存在或不是目录: {base_path_rel}"
    else:
        search_root = ws_resolved

    try:
        matches: list[str] = []
        for p in search_root.glob(pattern):
            if not str(p.resolve()).startswith(str(ws_resolved)):
                continue
            rel = p.relative_to(ws_resolved)
            matches.append(str(rel))
            if len(matches) >= MAX_RESULTS:
                break

        matches.sort()

        if not matches:
            return "未找到匹配文件"

        result = "\n".join(matches)
        if len(matches) >= MAX_RESULTS:
            result += f"\n\n... (结果已截断，共显示 {MAX_RESULTS} 条)"
        return result
    except Exception as exc:
        logger.exception("glob 匹配失败: %s", pattern)
        return f"glob 匹配失败: {exc}"
