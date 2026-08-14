from __future__ import annotations

from typing import Any


async def execute(args: dict[str, Any], context: dict[str, Any]) -> str:
    catalog = context.get("command_catalog")
    if catalog is None:
        return "斜杠命令目录不可用"
    query = str(args.get("query") or "").strip()
    if not query:
        return "请提供查询关键词"
    viewer = catalog.viewer_for_tool_args(args)
    if viewer is None:
        matches = await catalog.search_all(query)
        if not matches:
            return f"没有匹配“{query}”的斜杠命令"
        header = f"匹配到 {len(matches)} 条命令（完整目录，不限执行权限）："
    else:
        matches = await catalog.search(viewer, query)
        hint = catalog.format_viewer_hint(viewer)
        if not matches:
            return f"视角：{hint}\n没有匹配“{query}”的可用斜杠命令"
        header = f"视角：{hint}\n匹配到 {len(matches)} 条该视角可用命令："
    lines = [header]
    for meta in matches:
        desc = meta.description or "暂无说明"
        lines.append(
            f"- {catalog.format_name(meta)} — {desc}"
            f"（权限：{catalog.format_permission(meta)}）"
        )
    lines.append("需要限流、用法或文档时调用 commands.get；介绍时注明谁能用。")
    return "\n".join(lines)
