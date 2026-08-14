from __future__ import annotations

from typing import Any


async def execute(args: dict[str, Any], context: dict[str, Any]) -> str:
    catalog = context.get("command_catalog")
    if catalog is None:
        return "斜杠命令目录不可用"
    name = str(args.get("name") or "").strip()
    if not name:
        return "请提供命令名"
    viewer = catalog.viewer_from_mapping(context)
    meta = catalog.get(viewer, name)
    if meta is None:
        return "未找到命令，或当前发送者无权查看"
    return str(catalog.format_detail(meta))
