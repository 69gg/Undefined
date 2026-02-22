from __future__ import annotations
from typing import Any
import json


def _parse_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "on"}:
            return True
        if lowered in {"false", "0", "no", "off"}:
            return False
    return default


def _parse_int(
    value: Any,
    *,
    default: int | None,
    min_value: int,
    max_value: int,
) -> int | None:
    if value is None:
        return default
    parsed = int(value)
    if parsed < min_value or parsed > max_value:
        raise ValueError
    return parsed


def _parse_float(
    value: Any,
    *,
    default: float,
    min_value: float,
    max_value: float,
) -> float:
    if value is None:
        return default
    parsed = float(value)
    if parsed < min_value or parsed > max_value:
        raise ValueError
    return parsed


def _trim_text(text: str, max_chars: int) -> str:
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    return f"{text[: max_chars - 1].rstrip()}…"


async def execute(args: dict[str, Any], context: dict[str, Any]) -> str:
    km = context.get("knowledge_manager")
    if km is None:
        return "知识库功能未启用"
    kb = str(args.get("knowledge_base", "")).strip()
    query = str(args.get("query", "")).strip()
    if not kb or not query:
        return "错误：knowledge_base 和 query 不能为空"

    enable_rerank = _parse_bool(args.get("enable_rerank"), default=False)

    try:
        rerank_top_k = _parse_int(
            args.get("rerank_top_k"),
            default=None,
            min_value=1,
            max_value=200,
        )
        top_k = _parse_int(
            args.get("top_k"),
            default=None,
            min_value=1,
            max_value=500,
        )
        max_chars_per_item = _parse_int(
            args.get("max_chars_per_item"),
            default=220,
            min_value=20,
            max_value=8000,
        )
        min_relevance = _parse_float(
            args.get("min_relevance"),
            default=0.0,
            min_value=0.0,
            max_value=1.0,
        )
    except (TypeError, ValueError):
        return (
            "错误：top_k / rerank_top_k / max_chars_per_item / min_relevance 参数不合法"
        )

    include_rerank_score = _parse_bool(args.get("include_rerank_score"), default=True)
    source_keyword = str(args.get("source_keyword") or "").strip().lower()
    deduplicate = _parse_bool(args.get("deduplicate"), default=True)

    try:
        results = await km.semantic_search(
            kb,
            query,
            top_k=top_k,
            enable_rerank=enable_rerank
            if args.get("enable_rerank") is not None
            else None,
            rerank_top_k=rerank_top_k,
        )
    except Exception as exc:
        return f"语义搜索失败: {exc}"

    output: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for r in results:
        source = str((r.get("metadata") or {}).get("source", ""))
        if source_keyword and source_keyword not in source.lower():
            continue
        relevance = round(1 - float(r.get("distance", 0)), 4)
        if relevance < min_relevance:
            continue
        text = _trim_text(str(r.get("content", "")), int(max_chars_per_item or 0))
        if deduplicate:
            marker = (source, text)
            if marker in seen:
                continue
            seen.add(marker)
        item: dict[str, Any] = {
            "source": source,
            "text": text,
            "relevance": relevance,
        }
        if include_rerank_score and "rerank_score" in r:
            item["rerank_score"] = round(float(r.get("rerank_score", 0.0)), 6)
        output.append(item)

    payload = {
        "ok": True,
        "knowledge_base": kb,
        "query": query,
        "count": len(output),
        "items": output,
    }
    return json.dumps(payload, ensure_ascii=False)
