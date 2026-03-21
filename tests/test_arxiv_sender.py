from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from Undefined.arxiv.downloader import PaperDownloadResult
from Undefined.arxiv.models import PaperInfo
from Undefined.arxiv.sender import send_arxiv_paper
import Undefined.arxiv.sender as arxiv_sender


@pytest.fixture(autouse=True)
def _clear_inflight() -> None:
    arxiv_sender._INFLIGHT_SENDS.clear()


def _paper_info() -> PaperInfo:
    return PaperInfo(
        paper_id="2501.01234",
        title="Diffusion Policy for Robots",
        authors=("Alice", "Bob", "Carol"),
        summary="A concise summary of the paper.",
        published="2025-01-02T03:04:05Z",
        updated="2025-01-03T03:04:05Z",
        primary_category="cs.RO",
        abs_url="https://arxiv.org/abs/2501.01234",
        pdf_url="https://arxiv.org/pdf/2501.01234.pdf",
    )


def _sender() -> Any:
    return SimpleNamespace(
        send_group_message=AsyncMock(),
        send_private_message=AsyncMock(),
        send_group_file=AsyncMock(),
        send_private_file=AsyncMock(),
    )


@pytest.mark.asyncio
async def test_send_arxiv_paper_sends_info_and_pdf(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    sender = _sender()
    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")

    monkeypatch.setattr(
        arxiv_sender, "get_paper_info", AsyncMock(return_value=_paper_info())
    )
    monkeypatch.setattr(
        arxiv_sender,
        "download_paper_pdf",
        AsyncMock(
            return_value=(
                PaperDownloadResult(pdf_path, pdf_path.stat().st_size, "downloaded"),
                tmp_path,
            )
        ),
    )
    cleanup_mock = AsyncMock()
    monkeypatch.setattr(arxiv_sender, "cleanup_download_path", cleanup_mock)

    result = await send_arxiv_paper(
        paper_id="2501.01234",
        sender=sender,
        target_type="group",
        target_id=123456,
        max_file_size=100,
        author_preview_limit=2,
        summary_preview_chars=1000,
    )

    sender.send_group_message.assert_awaited_once()
    sender.send_group_file.assert_awaited_once()
    cleanup_mock.assert_awaited_once_with(tmp_path)
    assert "PDF" in result


@pytest.mark.asyncio
async def test_send_arxiv_paper_skips_pdf_failure_without_extra_prompt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    sender = _sender()

    monkeypatch.setattr(
        arxiv_sender, "get_paper_info", AsyncMock(return_value=_paper_info())
    )
    monkeypatch.setattr(
        arxiv_sender,
        "download_paper_pdf",
        AsyncMock(return_value=(PaperDownloadResult(None, None, "failed"), tmp_path)),
    )
    cleanup_mock = AsyncMock()
    monkeypatch.setattr(arxiv_sender, "cleanup_download_path", cleanup_mock)

    result = await send_arxiv_paper(
        paper_id="2501.01234",
        sender=sender,
        target_type="group",
        target_id=123456,
        max_file_size=100,
        author_preview_limit=20,
        summary_preview_chars=1000,
    )

    sender.send_group_message.assert_awaited_once()
    sender.send_group_file.assert_not_called()
    cleanup_mock.assert_awaited_once_with(tmp_path)
    assert "未附带 PDF" in result


@pytest.mark.asyncio
async def test_send_arxiv_paper_deduplicates_inflight_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sender = _sender()
    started = asyncio.Event()
    release = asyncio.Event()
    called = 0

    async def _fake_once(**_: object) -> str:
        nonlocal called
        called += 1
        started.set()
        await release.wait()
        return "ok"

    monkeypatch.setattr(arxiv_sender, "_send_arxiv_paper_once", _fake_once)

    first = asyncio.create_task(
        send_arxiv_paper(
            paper_id="2501.01234",
            sender=sender,
            target_type="group",
            target_id=123456,
            max_file_size=100,
            author_preview_limit=20,
            summary_preview_chars=1000,
        )
    )
    await started.wait()
    second = asyncio.create_task(
        send_arxiv_paper(
            paper_id="2501.01234",
            sender=sender,
            target_type="group",
            target_id=123456,
            max_file_size=100,
            author_preview_limit=20,
            summary_preview_chars=1000,
        )
    )

    release.set()
    first_result, second_result = await asyncio.gather(first, second)

    assert first_result == "ok"
    assert second_result == "ok"
    assert called == 1
