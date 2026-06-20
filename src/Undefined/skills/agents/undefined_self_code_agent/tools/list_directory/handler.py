from __future__ import annotations

from typing import Any

from Undefined.skills.agents.undefined_self_code_agent.tools._shared import (
    ALLOWED_DIRECTORIES,
    ALLOWED_ROOT_FILES,
    allowed_roots_text,
    clamp_int,
    list_allowed_directory_entries,
    resolve_allowed_path,
)
from Undefined.utils import io as async_io


async def execute(args: dict[str, Any], context: dict[str, Any]) -> str:
    """列出允许范围内的目录内容。"""

    path_arg = str(args.get("path") or "").strip()
    max_entries = clamp_int(args.get("max_entries"), 120, 1, 500)

    try:
        resolved = resolve_allowed_path(path_arg, context, allow_root=True)
    except PermissionError as exc:
        return f"权限不足：{exc}。{allowed_roots_text()}"
    except ValueError as exc:
        return f"错误：{exc}"

    if not path_arg:
        lines = ["允许访问范围："]
        lines.extend(f"📁 {name}/" for name in ALLOWED_DIRECTORIES)
        lines.extend(f"📄 {name}" for name in ALLOWED_ROOT_FILES)
        return "\n".join(lines)

    if not await async_io.exists(resolved.path):
        return f"目录不存在: {path_arg}"
    if not await async_io.is_dir(resolved.path):
        return f"错误：{path_arg} 不是目录"

    entries = await list_allowed_directory_entries(
        resolved.repo_root,
        resolved.path,
    )
    visible: list[str] = []
    for rel, is_dir in entries:
        icon = "📁" if is_dir else "📄"
        suffix = "/" if is_dir else ""
        visible.append(f"{icon} {rel}{suffix}")
        if len(visible) >= max_entries:
            break

    if not visible:
        return f"{resolved.rel_path or '.'}: 无可列出的允许内容"

    total_visible = len(entries)
    if total_visible > len(visible):
        visible.append(f"... 还有 {total_visible - len(visible)} 项")
    return "\n".join(visible)
