from __future__ import annotations

import json
from typing import Any


async def execute(args: dict[str, Any], context: dict[str, Any]) -> str:
    meme_service = context.get("meme_service")
    if meme_service is None or not getattr(meme_service, "enabled", False):
        return "表情包库未启用"

    query = str(args.get("query", "") or "").strip()
    keyword_query = str(args.get("keyword_query", "") or "").strip()
    semantic_query = str(args.get("semantic_query", "") or "").strip()
    query_mode = (
        str(
            args.get("query_mode")
            or getattr(meme_service, "default_query_mode", "hybrid")
        )
        .strip()
        .lower()
    )
    if query_mode not in {"keyword", "semantic", "hybrid"}:
        return "query_mode 只能是 keyword、semantic 或 hybrid"

    if not query and not keyword_query and not semantic_query:
        return "query、keyword_query、semantic_query 不能同时为空"

    try:
        top_k = int(args.get("top_k", 8))
    except (TypeError, ValueError):
        return "top_k 必须是整数"
    if top_k <= 0:
        return "top_k 必须大于 0"

    include_disabled = bool(args.get("include_disabled", False))
    payload = await meme_service.search_memes(
        query,
        query_mode=query_mode,
        keyword_query=keyword_query or None,
        semantic_query=semantic_query or None,
        top_k=top_k,
        include_disabled=include_disabled,
    )
    return json.dumps(payload, ensure_ascii=False)
