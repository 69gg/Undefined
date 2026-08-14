from __future__ import annotations

from typing import Any


async def execute(args: dict[str, Any], context: dict[str, Any]) -> str:
    catalog = context.get("command_catalog")
    if catalog is None:
        return "斜杠命令目录不可用"
    name = str(args.get("name") or "").strip()
    if not name:
        return "请提供命令名"
    meta = catalog.get_any(name)
    if meta is None:
        return "未找到命令"
    detail = str(catalog.format_detail(meta))
    viewer = catalog.viewer_for_tool_args(args)
    if viewer is None:
        return detail
    hint = catalog.format_viewer_hint(viewer)
    if catalog.get(viewer, name) is None:
        return f"视角：{hint}\n该视角无权使用该命令。\n\n{detail}"
    return f"视角：{hint}\n该视角可以使用该命令。\n\n{detail}"
