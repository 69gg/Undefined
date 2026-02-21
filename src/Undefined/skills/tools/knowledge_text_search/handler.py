from __future__ import annotations
from typing import Any
import json


async def execute(args: dict[str, Any], context: dict[str, Any]) -> str:
    km = context.get("knowledge_manager")
    if km is None:
        return "知识库功能未启用"
    kb = str(args.get("knowledge_base", "")).strip()
    keyword = str(args.get("keyword", "")).strip()
    if not kb or not keyword:
        return "错误：knowledge_base 和 keyword 不能为空"
    results = km.text_search(
        kb,
        keyword,
        max_lines=int(args.get("max_lines") or 20),
        max_chars=int(args.get("max_chars") or 2000),
    )
    return (
        json.dumps(results, ensure_ascii=False, indent=2)
        if results
        else "未找到匹配内容"
    )
