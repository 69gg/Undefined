from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import Undefined.arxiv.sender as arxiv_sender
from Undefined.arxiv.downloader import PaperDownloadResult
from Undefined.arxiv.client import SearchResponse
from Undefined.arxiv.models import PaperInfo
from Undefined.attachments import AttachmentRegistry
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
async def test_arxiv_paper_tool_uid_mode_registers_pdf(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")
    registry = AttachmentRegistry(
        registry_path=tmp_path / "attachment_registry.json",
        cache_dir=tmp_path / "attachments",
    )

    async def _fake_get_paper_info(
        _paper_id: str,
        *,
        context: dict[str, object] | None = None,
    ) -> PaperInfo:
        _ = context
        return PaperInfo(
            paper_id="2501.01234",
            title="UID Paper",
            authors=("Alice",),
            summary="summary",
            published="2025-01-02T00:00:00Z",
            updated="",
            primary_category="cs.AI",
            abs_url="https://arxiv.org/abs/2501.01234",
            pdf_url="https://arxiv.org/pdf/2501.01234.pdf",
        )

    async def _fake_download_paper_pdf(
        _info: PaperInfo,
        *,
        max_file_size_mb: int,
        context: dict[str, object] | None = None,
    ) -> tuple[PaperDownloadResult, Path]:
        _ = max_file_size_mb, context
        return (
            PaperDownloadResult(pdf_path, pdf_path.stat().st_size, "downloaded"),
            tmp_path,
        )

    cleanup_mock = AsyncMock()
    monkeypatch.setattr(arxiv_sender, "get_paper_info", _fake_get_paper_info)
    monkeypatch.setattr(arxiv_sender, "download_paper_pdf", _fake_download_paper_pdf)
    monkeypatch.setattr(arxiv_sender, "cleanup_download_path", cleanup_mock)

    result = await arxiv_paper.execute(
        {"paper_id": "2501.01234", "output_mode": "uid"},
        {
            "request_type": "private",
            "user_id": 12345,
            "attachment_registry": registry,
            "runtime_config": SimpleNamespace(
                arxiv_max_file_size=42,
                arxiv_author_preview_limit=7,
                arxiv_summary_preview_chars=2048,
            ),
        },
    )

    assert "UID Paper" in result
    assert '<attachment uid="file_' in result
    uid = result.split('<attachment uid="', 1)[1].split('"', 1)[0]
    record = registry.resolve(uid, "private:12345")
    assert record is not None
    assert record.display_name == "paper.pdf"
    assert Path(record.local_path or "").read_bytes() == b"%PDF-1.4"
    cleanup_mock.assert_awaited_once_with(tmp_path)


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
