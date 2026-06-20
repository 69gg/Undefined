from __future__ import annotations

from pathlib import Path
from typing import Any

from Undefined.skills.agents.undefined_self_code_agent.tools._shared import (
    DEFAULT_MAX_RESULTS,
    allowed_roots_text,
    clamp_int,
    format_relative,
    is_allowed_path,
    resolve_search_root,
)


async def execute(args: dict[str, Any], context: dict[str, Any]) -> str:
    """按 glob 模式查找允许范围内的文件。"""

    pattern = str(args.get("pattern") or "").strip()
    if not pattern:
        return "错误：pattern 不能为空"
    base_path = str(args.get("base_path") or "").strip()
    max_results = clamp_int(args.get("max_results"), DEFAULT_MAX_RESULTS, 1, 500)

    try:
        resolved = resolve_search_root(base_path, context)
    except PermissionError as exc:
        return f"权限不足：{exc}。{allowed_roots_text()}"
    except ValueError as exc:
        return f"错误：{exc}"

    if not resolved.path.exists():
        return f"路径不存在: {base_path or '.'}"

    search_roots: list[Path]
    if resolved.path == resolved.repo_root:
        search_roots = [resolved.repo_root]
    else:
        search_roots = [resolved.path]

    matches: list[str] = []
    seen: set[str] = set()
    try:
        for root in search_roots:
            candidates = root.glob(pattern)
            for candidate in candidates:
                if not candidate.is_file():
                    continue
                if not is_allowed_path(candidate, resolved.repo_root):
                    continue
                rel = format_relative(candidate, resolved.repo_root)
                if rel in seen:
                    continue
                seen.add(rel)
                matches.append(rel)
                if len(matches) >= max_results:
                    break
            if len(matches) >= max_results:
                break
    except ValueError as exc:
        return f"glob 模式无效: {exc}"

    if not matches:
        return f"未找到匹配的文件: {pattern}"
    matches.sort()
    result = "\n".join(matches)
    if len(matches) >= max_results:
        result += f"\n\n... (结果已截断，共显示 {max_results} 条)"
    return result
