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
    raw_enable_rerank = args.get("enable_rerank")
    enable_rerank: bool | None = None
    if isinstance(raw_enable_rerank, bool):
        enable_rerank = raw_enable_rerank
    elif isinstance(raw_enable_rerank, str):
        lowered = raw_enable_rerank.strip().lower()
        if lowered in {"true", "1", "yes", "on"}:
            enable_rerank = True
        elif lowered in {"false", "0", "no", "off"}:
            enable_rerank = False

    rerank_top_k: int | None = None
    raw_rerank_top_k = args.get("rerank_top_k")
    if raw_rerank_top_k is not None:
        try:
            rerank_top_k = int(raw_rerank_top_k)
        except (TypeError, ValueError):
            return "错误：rerank_top_k 必须是整数"
        if rerank_top_k <= 0:
            return "错误：rerank_top_k 必须大于 0"

    top_k: int | None = None
    raw_top_k = args.get("top_k")
    if raw_top_k is not None:
        try:
            top_k = int(raw_top_k)
        except (TypeError, ValueError):
            return "错误：top_k 必须是整数"
        if top_k <= 0:
            return "错误：top_k 必须大于 0"

    try:
        results = await km.semantic_search(
            kb,
            query,
            top_k=top_k,
            enable_rerank=enable_rerank,
            rerank_top_k=rerank_top_k,
        )
    except Exception as exc:
        return f"语义搜索失败: {exc}"
    if not results:
        return "未找到相关内容"
    output: list[dict[str, Any]] = []
    for r in results:
        item: dict[str, Any] = {
            "content": r["content"],
            "source": (r.get("metadata") or {}).get("source", ""),
            "relevance": round(1 - float(r.get("distance", 0)), 4),
        }
        if "rerank_score" in r:
            item["rerank_score"] = round(float(r.get("rerank_score", 0.0)), 6)
        output.append(item)
    return json.dumps(output, ensure_ascii=False, indent=2)
