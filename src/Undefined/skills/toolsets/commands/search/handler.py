from __future__ import annotations

from typing import Any


async def execute(args: dict[str, Any], context: dict[str, Any]) -> str:
    catalog = context.get("command_catalog")
    if catalog is None:
        return "斜杠命令目录不可用"
    query = str(args.get("query") or "").strip()
    if not query:
        return "请提供查询关键词"
    viewer = catalog.viewer_from_mapping(context)
    matches = catalog.search(viewer, query)
    if not matches:
        return f"没有匹配“{query}”的可用斜杠命令"
    lines = [f"匹配到 {len(matches)} 条可用命令："]
    for meta in matches:
        desc = meta.description or "暂无说明"
        lines.append(f"- {catalog.format_name(meta)} — {desc}")
    lines.append("需要限流、权限、用法或文档时调用 commands.get。")
    return "\n".join(lines)
