from __future__ import annotations
from typing import Any
import json


async def execute(args: dict[str, Any], context: dict[str, Any]) -> str:
    km = context.get("knowledge_manager")
    if km is None:
        return "知识库功能未启用"
    kb = str(args.get("knowledge_base", "")).strip()
    query = str(args.get("query", "")).strip()
    if not kb or not query:
        return "错误：knowledge_base 和 query 不能为空"
    try:
        results = await km.semantic_search(kb, query, top_k=args.get("top_k") or None)
    except Exception as exc:
        return f"语义搜索失败: {exc}"
    if not results:
        return "未找到相关内容"
    output = [
        {
            "content": r["content"],
            "source": (r.get("metadata") or {}).get("source", ""),
            "relevance": round(1 - float(r.get("distance", 0)), 4),
        }
        for r in results
    ]
    return json.dumps(output, ensure_ascii=False, indent=2)
