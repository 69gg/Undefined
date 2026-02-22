"""知识库工具 handler 测试。"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from Undefined.skills.tools.knowledge_list import handler as knowledge_list_handler
from Undefined.skills.tools.knowledge_semantic_search import (
    handler as knowledge_semantic_search_handler,
)
from Undefined.skills.tools.knowledge_text_search import (
    handler as knowledge_text_search_handler,
)


async def test_knowledge_list_handler_returns_compact_payload() -> None:
    km = MagicMock()
    km.list_knowledge_base_infos.return_value = [
        {"name": "kb_alpha", "intro": "alpha", "has_intro": True},
        {"name": "kb_beta", "intro": "beta", "has_intro": True},
    ]
    result = await knowledge_list_handler.execute(
        {"name_keyword": "alpha", "include_has_intro": True},
        {"knowledge_manager": km},
    )
    payload = json.loads(result)
    assert payload["ok"] is True
    assert payload["count"] == 1
    assert payload["items"][0]["name"] == "kb_alpha"
    assert payload["items"][0]["has_intro"] is True


async def test_knowledge_text_search_handler_supports_filters_and_trim() -> None:
    km = MagicMock()
    km.text_search.return_value = [
        {
            "source": "texts/docs/faq.md",
            "line": 8,
            "content": "这是一段很长很长的文本，用于测试裁剪行为是否生效",
        }
    ]
    result = await knowledge_text_search_handler.execute(
        {
            "knowledge_base": "kb1",
            "keyword": "测试",
            "max_chars_per_item": 20,
            "source_keyword": "docs/",
            "case_sensitive": True,
        },
        {"knowledge_manager": km},
    )
    payload = json.loads(result)
    assert payload["ok"] is True
    assert payload["count"] == 1
    assert payload["items"][0]["source"] == "texts/docs/faq.md"
    assert payload["items"][0]["line"] == 8
    assert payload["items"][0]["text"].endswith("…")
    km.text_search.assert_called_once_with(
        "kb1",
        "测试",
        max_lines=20,
        max_chars=2000,
        case_sensitive=True,
        source_keyword="docs/",
    )


async def test_knowledge_semantic_search_handler_applies_post_filters() -> None:
    km = SimpleNamespace()
    km.semantic_search = AsyncMock(
        return_value=[
            {
                "content": "第一条",
                "metadata": {"source": "texts/docs/a.md"},
                "distance": 0.05,
                "rerank_score": 0.88,
            },
            {
                "content": "第一条",
                "metadata": {"source": "texts/docs/a.md"},
                "distance": 0.05,
                "rerank_score": 0.87,
            },
            {
                "content": "低相关度",
                "metadata": {"source": "texts/docs/b.md"},
                "distance": 0.9,
            },
        ]
    )
    result = await knowledge_semantic_search_handler.execute(
        {
            "knowledge_base": "kb1",
            "query": "查询",
            "min_relevance": 0.5,
            "source_keyword": "docs/",
            "deduplicate": True,
        },
        {"knowledge_manager": km},
    )
    payload = json.loads(result)
    assert payload["ok"] is True
    assert payload["count"] == 1
    assert payload["items"][0]["source"] == "texts/docs/a.md"
    assert payload["items"][0]["relevance"] == 0.95
