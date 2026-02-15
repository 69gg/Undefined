from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

MAX_MATCHES_DEFAULT = 100
MAX_LINE_LEN = 500


def _format_line(line: str, max_len: int = MAX_LINE_LEN) -> str:
    """格式化行内容，超长则截断。"""
    if len(line) > max_len:
        return line[:max_len] + "..."
    return line


def _collect_context_matches(
    lines: list[str],
    match_line_numbers: list[int],
    context_before: int,
    context_after: int,
) -> list[tuple[int, str, bool]]:
    """收集匹配行及其上下文。

    返回: [(line_number, line_content, is_match), ...]
    """
    result: list[tuple[int, str, bool]] = []
    included_lines: set[int] = set()

    for match_lineno in match_line_numbers:
        # 计算上下文范围
        start = max(1, match_lineno - context_before)
        end = min(len(lines), match_lineno + context_after)

        # 收集这个范围内的所有行
        for lineno in range(start, end + 1):
            if lineno not in included_lines:
                included_lines.add(lineno)
                is_match = lineno == match_lineno
                result.append((lineno, lines[lineno - 1], is_match))

    # 按行号排序
    result.sort(key=lambda x: x[0])
    return result


async def execute(args: dict[str, Any], context: dict[str, Any]) -> str:
    """在工作区内搜索文件内容。支持上下文行显示。"""

    pattern = str(args.get("pattern", "")).strip()
    path_rel = str(args.get("path", "")).strip()
    is_regex = bool(args.get("is_regex", False))
    case_sensitive = bool(args.get("case_sensitive", True))
    max_matches = int(args.get("max_matches", MAX_MATCHES_DEFAULT))
    output_mode = str(args.get("output_mode", "matches")).strip().lower()

    # 上下文参数
    context_param = args.get("context")
    context_before = args.get("context_before", 0)
    context_after = args.get("context_after", 0)

    if context_param is not None:
        context_before = context_after = int(context_param)
    else:
        context_before = int(context_before)
        context_after = int(context_after)

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

    # 根据 output_mode 收集不同的结果
    file_matches: dict[str, list[int]] = {}  # 文件 -> 匹配行号列表
    file_lines: dict[str, list[str]] = {}  # 文件 -> 所有行
    total_matches = 0

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

            rel = str(file_path.relative_to(ws_resolved))
            lines = text.splitlines()
            match_line_numbers: list[int] = []

            for lineno, line in enumerate(lines, 1):
                if compiled.search(line):
                    match_line_numbers.append(lineno)
                    total_matches += 1
                    if total_matches >= max_matches:
                        break

            if match_line_numbers:
                file_matches[rel] = match_line_numbers
                file_lines[rel] = lines

            if total_matches >= max_matches:
                break

    except Exception as exc:
        logger.exception("grep 搜索失败")
        return f"搜索失败: {exc}"

    if not file_matches:
        return "未找到匹配内容"

    # 根据 output_mode 生成输出
    if output_mode == "files":
        result = "\n".join(sorted(file_matches.keys()))
        if total_matches >= max_matches:
            result += f"\n\n... (结果已截断，共显示 {max_matches} 条匹配)"
        return result

    elif output_mode == "count":
        count_lines: list[str] = []
        for rel_path in sorted(file_matches.keys()):
            count = len(file_matches[rel_path])
            count_lines.append(f"{rel_path}: {count}")
        result = "\n".join(count_lines)
        if total_matches >= max_matches:
            result += f"\n\n... (结果已截断，共显示 {max_matches} 条匹配)"
        return result

    else:  # matches mode
        output_lines: list[str] = []

        for rel_path in sorted(file_matches.keys()):
            match_line_numbers = file_matches[rel_path]
            lines_list = file_lines[rel_path]

            if context_before == 0 and context_after == 0:
                # 无上下文，简单输出
                for lineno in match_line_numbers:
                    line = lines_list[lineno - 1]
                    display = _format_line(line)
                    output_lines.append(f"{rel_path}:{lineno}:{display}")
            else:
                # 有上下文，收集上下文行
                context_matches = _collect_context_matches(
                    lines_list, match_line_numbers, context_before, context_after
                )

                output_lines.append(f"\n=== {rel_path} ===")
                prev_lineno = 0
                for lineno, line, is_match in context_matches:
                    # 如果行号不连续，插入分隔符
                    if prev_lineno > 0 and lineno > prev_lineno + 1:
                        output_lines.append("--")

                    display = _format_line(line)
                    separator = ":" if is_match else "-"
                    output_lines.append(f"{lineno}{separator}{display}")
                    prev_lineno = lineno

        result = "\n".join(output_lines)
        if total_matches >= max_matches:
            result += f"\n\n... (结果已截断，共显示 {max_matches} 条匹配)"
        return result
