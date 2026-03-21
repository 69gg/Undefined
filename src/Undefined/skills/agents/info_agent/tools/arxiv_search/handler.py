from __future__ import annotations

import logging
from typing import Any

from Undefined.arxiv.client import search_papers

logger = logging.getLogger(__name__)


def _normalize_space(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _to_non_negative_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    if parsed < 0:
        return default
    return parsed


def _preview_authors(authors: tuple[str, ...], limit: int) -> str:
    if not authors:
        return ""
    if len(authors) <= limit:
        return "、".join(authors)
    return f"{'、'.join(authors[:limit])} 等{len(authors)}位作者"


async def execute(args: dict[str, Any], context: dict[str, Any]) -> str:
    query = _normalize_space(args.get("msg"))
    if not query:
        return "请提供搜索内容。"

    limit = _to_non_negative_int(args.get("n", 5), 5)
    limit = max(1, min(limit, 20))
    start = _to_non_negative_int(args.get("start", 0), 0)

    runtime_config = context.get("runtime_config")
    author_preview_limit = 20
    if runtime_config is not None:
        author_preview_limit = getattr(runtime_config, "arxiv_author_preview_limit", 20)

    try:
        response = await search_papers(
            query,
            start=start,
            max_results=limit,
            context={"request_id": context.get("request_id", "-")},
        )
    except Exception as exc:
        logger.exception("[arxiv_search] 搜索失败: %s", exc)
        return "arXiv 搜索失败，请稍后重试"

    if not response.items:
        return f"未找到与“{query}”相关的 arXiv 论文。"

    header = "🔍 arXiv 搜索结果"
    if response.total_results is not None:
        header += f"（total={response.total_results}"
        if response.start_index is not None:
            header += f", start={response.start_index}"
        header += "）"

    lines = [header]
    for idx, item in enumerate(response.items, start=1):
        lines.append(f"{idx}. {item.title or f'arXiv:{item.paper_id}'}")
        lines.append(f"   ID: {item.paper_id}")
        authors = _preview_authors(item.authors, author_preview_limit)
        if authors:
            lines.append(f"   作者: {authors}")
        if item.primary_category:
            lines.append(f"   分类: {item.primary_category}")
        if item.published:
            lines.append(f"   日期: {item.published[:10]}")
        lines.append(f"   链接: {item.abs_url}")

    return "\n".join(lines)
