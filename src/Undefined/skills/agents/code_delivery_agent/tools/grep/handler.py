from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

MAX_MATCHES_DEFAULT = 100
MAX_LINE_LEN = 500


async def execute(args: dict[str, Any], context: dict[str, Any]) -> str:
    """在工作区内搜索文件内容。"""

    pattern = str(args.get("pattern", "")).strip()
    path_rel = str(args.get("path", "")).strip()
    is_regex = bool(args.get("is_regex", False))
    case_sensitive = bool(args.get("case_sensitive", True))
    max_matches = int(args.get("max_matches", MAX_MATCHES_DEFAULT))

    if not pattern:
        return "错误：pattern 不能为空"

    workspace: Path | None = context.get("workspace")
    if not workspace:
        return "错误：workspace 未设置"

    ws_resolved = workspace.resolve()

    if path_rel:
        search_root = (workspace / path_rel).resolve()
        if not str(search_root).startswith(str(ws_resolved)):
            return "错误：path 越界"
    else:
        search_root = ws_resolved

    flags = 0 if case_sensitive else re.IGNORECASE
    try:
        if is_regex:
            compiled = re.compile(pattern, flags)
        else:
            compiled = re.compile(re.escape(pattern), flags)
    except re.error as exc:
        return f"正则表达式错误: {exc}"

    matches: list[str] = []
    try:
        files = search_root.rglob("*") if search_root.is_dir() else [search_root]
        for file_path in files:
            if not file_path.is_file():
                continue
            if not str(file_path.resolve()).startswith(str(ws_resolved)):
                continue
            try:
                text = file_path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue

            rel = file_path.relative_to(ws_resolved)
            for lineno, line in enumerate(text.splitlines(), 1):
                if compiled.search(line):
                    display = line[:MAX_LINE_LEN]
                    if len(line) > MAX_LINE_LEN:
                        display += "..."
                    matches.append(f"{rel}:{lineno}:{display}")
                    if len(matches) >= max_matches:
                        break
            if len(matches) >= max_matches:
                break
    except Exception as exc:
        logger.exception("grep 搜索失败")
        return f"搜索失败: {exc}"

    if not matches:
        return "未找到匹配内容"

    result = "\n".join(matches)
    if len(matches) >= max_matches:
        result += f"\n\n... (结果已截断，共显示 {max_matches} 条)"
    return result
