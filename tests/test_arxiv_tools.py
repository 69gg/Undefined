from __future__ import annotations

from types import SimpleNamespace

import pytest

from Undefined.arxiv.client import SearchResponse
from Undefined.arxiv.models import PaperInfo
from Undefined.skills.agents.info_agent.tools.arxiv_search import (
    handler as arxiv_search,
)
from Undefined.skills.tools.arxiv_paper import handler as arxiv_paper


@pytest.mark.asyncio
async def test_arxiv_paper_tool_uses_runtime_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    async def _fake_send_arxiv_paper(**kwargs: object) -> str:
        captured.update(kwargs)
        return "ok"

    monkeypatch.setattr(arxiv_paper, "send_arxiv_paper", _fake_send_arxiv_paper)

    context = {
        "request_type": "group",
        "group_id": 123456,
        "sender": object(),
        "request_id": "req-1",
        "runtime_config": SimpleNamespace(
            arxiv_max_file_size=42,
            arxiv_author_preview_limit=7,
            arxiv_summary_preview_chars=2048,
        ),
    }
    result = await arxiv_paper.execute({"paper_id": "2501.01234"}, context)

    assert result == "ok"
    assert captured["paper_id"] == "2501.01234"
    assert captured["target_type"] == "group"
    assert captured["target_id"] == 123456
    assert captured["max_file_size"] == 42
    assert captured["author_preview_limit"] == 7
    assert captured["summary_preview_chars"] == 2048


@pytest.mark.asyncio
async def test_arxiv_search_tool_formats_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_search_papers(
        _query: str,
        *,
        start: int,
        max_results: int,
        context: dict[str, object] | None = None,
    ) -> SearchResponse:
        assert start == 2
        assert max_results == 3
        assert context == {"request_id": "req-2"}
        return SearchResponse(
            items=(
                PaperInfo(
                    paper_id="2501.01234",
                    title="First Paper",
                    authors=("Alice", "Bob", "Carol"),
                    summary="",
                    published="2025-01-02T03:04:05Z",
                    updated="",
                    primary_category="cs.RO",
                    abs_url="https://arxiv.org/abs/2501.01234",
                    pdf_url="https://arxiv.org/pdf/2501.01234.pdf",
                ),
            ),
            total_results=123,
            start_index=2,
        )

    monkeypatch.setattr(arxiv_search, "search_papers", _fake_search_papers)

    result = await arxiv_search.execute(
        {"msg": "diffusion policy", "n": 3, "start": 2},
        {
            "request_id": "req-2",
            "runtime_config": SimpleNamespace(arxiv_author_preview_limit=2),
        },
    )

    assert "First Paper" in result
    assert "ID: 2501.01234" in result
    assert "Alice、Bob 等3位作者" in result
    assert "total=123" in result
