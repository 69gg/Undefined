from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

from Undefined.skills.agents.undefined_self_code_agent.tools._shared import (
    DEFAULT_MAX_MATCHES,
    allowed_roots_text,
    clamp_int,
    compile_pattern,
    format_relative,
    iter_allowed_files,
    path_matches_include,
    read_text_file,
    resolve_search_root,
    trim_line,
)
from Undefined.utils import io as async_io

logger = logging.getLogger(__name__)


async def execute(args: dict[str, Any], context: dict[str, Any]) -> str:
    """在允许范围内搜索文本内容。"""

    pattern = str(args.get("pattern") or "").strip()
    if not pattern:
        return "错误：pattern 不能为空"

    path_arg = str(args.get("path") or "").strip()
    include = str(args.get("include") or "").strip()
    is_regex = bool(args.get("is_regex", False))
    case_sensitive = bool(args.get("case_sensitive", True))
    max_matches = clamp_int(args.get("max_matches"), DEFAULT_MAX_MATCHES, 1, 500)

    try:
        resolved = resolve_search_root(path_arg, context)
    except PermissionError as exc:
        return f"权限不足：{exc}。{allowed_roots_text()}"
    except ValueError as exc:
        return f"错误：{exc}"

    if not await async_io.exists(resolved.path):
        return f"路径不存在: {path_arg or '.'}"

    try:
        compiled = compile_pattern(
            pattern,
            is_regex=is_regex,
            case_sensitive=case_sensitive,
        )
    except re.error as exc:
        return f"正则表达式错误: {exc}"

    matches: list[str] = []
    try:
        async for file_path in iter_allowed_files(resolved.repo_root, resolved.path):
            if not path_matches_include(file_path, resolved.repo_root, include):
                continue
            try:
                text, _truncated, _size = await asyncio.to_thread(
                    read_text_file,
                    file_path,
                )
            except (OSError, UnicodeError):
                continue
            rel = format_relative(file_path, resolved.repo_root)
            for line_number, line in enumerate(text.splitlines(), start=1):
                if compiled.search(line):
                    matches.append(f"{rel}:{line_number}:{trim_line(line.rstrip())}")
                    if len(matches) >= max_matches:
                        break
            if len(matches) >= max_matches:
                break
    except Exception as exc:
        logger.exception("搜索失败: %s", pattern)
        return f"搜索失败: {exc}"

    if not matches:
        return f"未找到匹配: {pattern}"

    result = "\n".join(matches)
    if len(matches) >= max_matches:
        result += f"\n\n... (结果已截断，共显示 {max_matches} 条匹配)"
    return result
