from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import fitz
import pytest

from Undefined.skills.agents.file_analysis_agent.tools.describe_pdf_page import (
    handler as describe_pdf_page,
)


def _make_pdf(path: Path, page_count: int = 3) -> None:
    doc = fitz.open()
    for index in range(page_count):
        page = doc.new_page()
        page.insert_text((72, 72), f"Page {index + 1}")
    doc.save(str(path))
    doc.close()


@pytest.mark.asyncio
async def test_describe_pdf_page_supports_mixed_page_range(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pdf_path = tmp_path / "demo.pdf"
    _make_pdf(pdf_path, page_count=5)
    calls: list[dict[str, Any]] = []

    async def _fake_analyze(args: dict[str, Any], context: dict[str, Any]) -> str:
        _ = context
        calls.append(args)
        return f"分析 {Path(str(args['file_path'])).name}"

    monkeypatch.setattr(
        cast(Any, describe_pdf_page).analyze_multimodal_handler,
        "execute",
        _fake_analyze,
    )

    result = await describe_pdf_page.execute(
        {
            "file_path": str(pdf_path),
            "page_range": "1,3-4",
            "prompt": "描述图表",
        },
        {"download_cache_dir": tmp_path / "downloads", "ai_client": object()},
    )

    assert "本次视觉分析页码：1, 3, 4" in result
    assert "--- 第 1 页 ---" in result
    assert "--- 第 3 页 ---" in result
    assert "--- 第 4 页 ---" in result
    assert len(calls) == 3
    assert {call["media_type"] for call in calls} == {"image"}
    assert {call["prompt"] for call in calls} == {"描述图表"}
    assert not list((tmp_path / "downloads").glob("**/*.png"))


@pytest.mark.asyncio
async def test_describe_pdf_page_rejects_too_many_pages(tmp_path: Path) -> None:
    pdf_path = tmp_path / "demo.pdf"
    _make_pdf(pdf_path, page_count=8)

    result = await describe_pdf_page.execute(
        {"file_path": str(pdf_path), "page_range": "1-6"},
        {"download_cache_dir": tmp_path / "downloads", "ai_client": object()},
    )

    assert "单次最多分析 5 页" in result


@pytest.mark.asyncio
async def test_describe_pdf_page_rejects_out_of_range_page(tmp_path: Path) -> None:
    pdf_path = tmp_path / "demo.pdf"
    _make_pdf(pdf_path, page_count=2)

    result = await describe_pdf_page.execute(
        {"file_path": str(pdf_path), "page_range": "3"},
        {"download_cache_dir": tmp_path / "downloads", "ai_client": object()},
    )

    assert "超出范围" in result
