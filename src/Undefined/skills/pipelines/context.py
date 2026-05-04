"""构建管线执行上下文。"""

from __future__ import annotations

from typing import Any


def build_pipeline_context(
    handler: Any,
    *,
    target_id: int,
    target_type: str,
    text: str,
    message_content: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    return {
        "config": handler.config,
        "sender": handler.sender,
        "onebot": handler.onebot,
        "target_id": target_id,
        "target_type": target_type,
        "text": text,
        "message_content": message_content,
        "extract_bilibili_ids": handler._extract_bilibili_ids,
        "extract_arxiv_ids": handler._extract_arxiv_ids,
        "extract_github_repo_ids": handler._extract_github_repo_ids,
        "handle_bilibili_extract": handler._handle_bilibili_extract,
        "handle_arxiv_extract": handler._handle_arxiv_extract,
        "handle_github_extract": handler._handle_github_extract,
    }
