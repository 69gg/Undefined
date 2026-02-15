from __future__ import annotations

import logging
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _should_exclude(name: str, patterns: list[str]) -> bool:
    """检查文件/目录名是否匹配排除模式。"""
    for pattern in patterns:
        if fnmatch(name, pattern):
            return True
    return False


def _build_tree(
    path: Path,
    prefix: str,
    is_last: bool,
    max_depth: int,
    current_depth: int,
    show_hidden: bool,
    exclude_patterns: list[str],
    lines: list[str],
) -> None:
    """递归构建目录树。"""
    if max_depth > 0 and current_depth > max_depth:
        return

    try:
        entries = sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    except PermissionError:
        lines.append(f"{prefix}{'└── ' if is_last else '├── '}[权限拒绝]")
        return
    except Exception as exc:
        lines.append(f"{prefix}{'└── ' if is_last else '├── '}[错误: {exc}]")
        return

    # 过滤条目
    filtered_entries: list[Path] = []
    for entry in entries:
        name = entry.name
        # 排除隐藏文件（如果不显示）
        if not show_hidden and name.startswith("."):
            continue
        # 排除匹配的模式
        if _should_exclude(name, exclude_patterns):
            continue
        filtered_entries.append(entry)

    for idx, entry in enumerate(filtered_entries):
        is_last_entry = idx == len(filtered_entries) - 1
        connector = "└── " if is_last_entry else "├── "
        name = entry.name

        if entry.is_dir():
            lines.append(f"{prefix}{connector}{name}/")
            extension = "    " if is_last_entry else "│   "
            _build_tree(
                entry,
                prefix + extension,
                is_last_entry,
                max_depth,
                current_depth + 1,
                show_hidden,
                exclude_patterns,
                lines,
            )
        else:
            lines.append(f"{prefix}{connector}{name}")


async def execute(args: dict[str, Any], context: dict[str, Any]) -> str:
    """显示目录树结构。"""

    rel_path = str(args.get("path", "")).strip()
    max_depth = int(args.get("max_depth", 5))
    show_hidden = bool(args.get("show_hidden", False))
    exclude_patterns = args.get("exclude_patterns", [])

    if not isinstance(exclude_patterns, list):
        exclude_patterns = []
    exclude_patterns = [str(p) for p in exclude_patterns]

    workspace: Path | None = context.get("workspace")
    if not workspace:
        return "错误：workspace 未设置"

    if rel_path:
        target_path = (workspace / rel_path).resolve()
    else:
        target_path = workspace.resolve()

    if not str(target_path).startswith(str(workspace.resolve())):
        return "错误：路径越界，只能访问 /workspace 下的目录"

    if not target_path.exists():
        return f"路径不存在: {rel_path or '.'}"
    if not target_path.is_dir():
        return f"错误：{rel_path or '.'} 不是目录"

    lines: list[str] = [str(target_path.relative_to(workspace.resolve())) or "."]
    _build_tree(
        target_path,
        "",
        True,
        max_depth,
        1,
        show_hidden,
        exclude_patterns,
        lines,
    )

    result = "\n".join(lines)
    if max_depth > 0:
        result += f"\n\n(最大深度: {max_depth})"
    return result
