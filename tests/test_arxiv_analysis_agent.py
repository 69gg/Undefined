"""arxiv_analysis_agent 单元测试。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest


# ---------------------------------------------------------------------------
# config.json / callable.json 结构检查
# ---------------------------------------------------------------------------

AGENT_DIR = (
    Path(__file__).resolve().parent.parent
    / "src"
    / "Undefined"
    / "skills"
    / "agents"
    / "arxiv_analysis_agent"
)


def _load_json(name: str) -> dict[str, Any]:
    result: dict[str, Any] = json.loads((AGENT_DIR / name).read_text(encoding="utf-8"))
    return result


class TestAgentConfig:
    def test_config_json_schema(self) -> None:
        cfg = _load_json("config.json")
        assert cfg["type"] == "function"
        func = cfg["function"]
        assert func["name"] == "arxiv_analysis_agent"
        assert "paper_id" in func["parameters"]["properties"]
        assert "paper_id" in func["parameters"]["required"]

    def test_callable_json(self) -> None:
        cfg = _load_json("callable.json")
        assert cfg["enabled"] is True
        assert isinstance(cfg["allowed_callers"], list)
        assert len(cfg["allowed_callers"]) > 0

    def test_tools_exist(self) -> None:
        tools_dir = AGENT_DIR / "tools"
        assert (tools_dir / "fetch_paper" / "config.json").exists()
        assert (tools_dir / "fetch_paper" / "handler.py").exists()
        assert (tools_dir / "read_paper_pages" / "config.json").exists()
        assert (tools_dir / "read_paper_pages" / "handler.py").exists()

    def test_prompt_md_exists(self) -> None:
        assert (AGENT_DIR / "prompt.md").exists()
        content = (AGENT_DIR / "prompt.md").read_text(encoding="utf-8")
        assert len(content) > 100


# ---------------------------------------------------------------------------
# handler.py
# ---------------------------------------------------------------------------


class TestHandler:
    @pytest.mark.asyncio
    async def test_empty_paper_id(self) -> None:
        from Undefined.skills.agents.arxiv_analysis_agent.handler import execute

        result = await execute({"paper_id": ""}, {})
        assert "请提供" in result

    @pytest.mark.asyncio
    async def test_invalid_paper_id(self) -> None:
        from Undefined.skills.agents.arxiv_analysis_agent.handler import execute

        result = await execute({"paper_id": "not-a-valid-id"}, {})
        assert "无法解析" in result

    @pytest.mark.asyncio
    async def test_valid_paper_id_calls_runner(self) -> None:
        from Undefined.skills.agents.arxiv_analysis_agent.handler import execute

        mock_result = "分析结果"
        with patch(
            "Undefined.skills.agents.arxiv_analysis_agent.handler.run_agent_with_tools",
            new_callable=AsyncMock,
            return_value=mock_result,
        ) as mock_run:
            result = await execute(
                {"paper_id": "2301.07041", "prompt": "分析方法论"},
                {"request_id": "test-123"},
            )
            assert result == mock_result
            mock_run.assert_awaited_once()
            call_kwargs = mock_run.call_args[1]
            assert call_kwargs["agent_name"] == "arxiv_analysis_agent"
            assert "分析方法论" in call_kwargs["user_content"]

    @pytest.mark.asyncio
    async def test_url_input_normalized(self) -> None:
        from Undefined.skills.agents.arxiv_analysis_agent.handler import execute

        with patch(
            "Undefined.skills.agents.arxiv_analysis_agent.handler.run_agent_with_tools",
            new_callable=AsyncMock,
            return_value="ok",
        ):
            ctx: dict[str, Any] = {}
            await execute(
                {"paper_id": "https://arxiv.org/abs/2301.07041"},
                ctx,
            )
            assert ctx["arxiv_paper_id"] == "2301.07041"


# ---------------------------------------------------------------------------
# fetch_paper tool
# ---------------------------------------------------------------------------


def _make_paper_info(
    paper_id: str = "2301.07041",
) -> Any:
    from Undefined.arxiv.models import PaperInfo

    return PaperInfo(
        paper_id=paper_id,
        title="Test Paper Title",
        authors=("Author A", "Author B"),
        summary="This is a test abstract.",
        published="2023-01-17T00:00:00Z",
        updated="2023-01-18T00:00:00Z",
        primary_category="cs.AI",
        abs_url=f"https://arxiv.org/abs/{paper_id}",
        pdf_url=f"https://arxiv.org/pdf/{paper_id}.pdf",
    )


class TestFetchPaper:
    @pytest.mark.asyncio
    async def test_empty_paper_id(self) -> None:
        from Undefined.skills.agents.arxiv_analysis_agent.tools.fetch_paper.handler import (
            execute,
        )

        result = await execute({"paper_id": ""}, {})
        assert "错误" in result

    @pytest.mark.asyncio
    async def test_metadata_only_on_download_failure(self) -> None:
        from Undefined.skills.agents.arxiv_analysis_agent.tools.fetch_paper.handler import (
            execute,
        )

        paper = _make_paper_info()
        with (
            patch(
                "Undefined.skills.agents.arxiv_analysis_agent.tools.fetch_paper.handler.get_paper_info",
                new_callable=AsyncMock,
                return_value=paper,
            ),
            patch(
                "Undefined.skills.agents.arxiv_analysis_agent.tools.fetch_paper.handler.download_paper_pdf",
                new_callable=AsyncMock,
                side_effect=RuntimeError("network error"),
            ),
        ):
            result = await execute({"paper_id": "2301.07041"}, {})
            assert "Test Paper Title" in result
            assert "Author A" in result
            assert "PDF 下载失败" in result

    @pytest.mark.asyncio
    async def test_paper_not_found(self) -> None:
        from Undefined.skills.agents.arxiv_analysis_agent.tools.fetch_paper.handler import (
            execute,
        )

        with patch(
            "Undefined.skills.agents.arxiv_analysis_agent.tools.fetch_paper.handler.get_paper_info",
            new_callable=AsyncMock,
            return_value=None,
        ):
            result = await execute({"paper_id": "9999.99999"}, {})
            assert "未找到" in result

    @pytest.mark.asyncio
    async def test_successful_fetch_with_pdf(self, tmp_path: Path) -> None:
        from Undefined.skills.agents.arxiv_analysis_agent.tools.fetch_paper.handler import (
            execute,
        )

        paper = _make_paper_info()
        pdf_path = tmp_path / "test.pdf"

        import fitz

        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 72), "Hello world")
        doc.save(str(pdf_path))
        doc.close()

        from Undefined.arxiv.downloader import PaperDownloadResult

        download_result = PaperDownloadResult(
            path=pdf_path, size_bytes=1024, status="downloaded"
        )

        with (
            patch(
                "Undefined.skills.agents.arxiv_analysis_agent.tools.fetch_paper.handler.get_paper_info",
                new_callable=AsyncMock,
                return_value=paper,
            ),
            patch(
                "Undefined.skills.agents.arxiv_analysis_agent.tools.fetch_paper.handler.download_paper_pdf",
                new_callable=AsyncMock,
                return_value=(download_result, tmp_path),
            ),
        ):
            ctx: dict[str, Any] = {}
            result = await execute({"paper_id": "2301.07041"}, ctx)
            assert "Test Paper Title" in result
            assert "1 页" in result
            assert ctx["_arxiv_pdf_path"] == str(pdf_path)
            assert ctx["_arxiv_pdf_pages"] == 1


# ---------------------------------------------------------------------------
# read_paper_pages tool
# ---------------------------------------------------------------------------


class TestReadPaperPages:
    @pytest.mark.asyncio
    async def test_no_pdf_downloaded(self) -> None:
        from Undefined.skills.agents.arxiv_analysis_agent.tools.read_paper_pages.handler import (
            execute,
        )

        result = await execute({"start_page": 1, "end_page": 1}, {})
        assert "先调用 fetch_paper" in result

    @pytest.mark.asyncio
    async def test_read_single_page(self, tmp_path: Path) -> None:
        from Undefined.skills.agents.arxiv_analysis_agent.tools.read_paper_pages.handler import (
            execute,
        )

        import fitz

        pdf_path = tmp_path / "paper.pdf"
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 72), "Page 1 content")
        page2 = doc.new_page()
        page2.insert_text((72, 72), "Page 2 content")
        doc.save(str(pdf_path))
        doc.close()

        ctx: dict[str, Any] = {
            "_arxiv_pdf_path": str(pdf_path),
            "_arxiv_pdf_pages": 2,
        }
        result = await execute({"start_page": 1, "end_page": 1}, ctx)
        assert "第 1 页" in result
        assert "Page 1 content" in result
        assert "Page 2 content" not in result

    @pytest.mark.asyncio
    async def test_read_page_range(self, tmp_path: Path) -> None:
        from Undefined.skills.agents.arxiv_analysis_agent.tools.read_paper_pages.handler import (
            execute,
        )

        import fitz

        pdf_path = tmp_path / "paper.pdf"
        doc = fitz.open()
        for i in range(3):
            page = doc.new_page()
            page.insert_text((72, 72), f"Content of page {i + 1}")
        doc.save(str(pdf_path))
        doc.close()

        ctx: dict[str, Any] = {
            "_arxiv_pdf_path": str(pdf_path),
            "_arxiv_pdf_pages": 3,
        }
        result = await execute({"start_page": 1, "end_page": 3}, ctx)
        assert "第 1-3 页" in result or "第 1 页" in result
        assert "Content of page 1" in result
        assert "Content of page 3" in result

    @pytest.mark.asyncio
    async def test_out_of_range_page(self, tmp_path: Path) -> None:
        from Undefined.skills.agents.arxiv_analysis_agent.tools.read_paper_pages.handler import (
            execute,
        )

        import fitz

        pdf_path = tmp_path / "paper.pdf"
        doc = fitz.open()
        doc.new_page()
        doc.save(str(pdf_path))
        doc.close()

        ctx: dict[str, Any] = {
            "_arxiv_pdf_path": str(pdf_path),
            "_arxiv_pdf_pages": 1,
        }
        result = await execute({"start_page": 5, "end_page": 10}, ctx)
        assert "错误" in result

    @pytest.mark.asyncio
    async def test_invalid_page_numbers(self) -> None:
        from Undefined.skills.agents.arxiv_analysis_agent.tools.read_paper_pages.handler import (
            execute,
        )

        ctx: dict[str, Any] = {
            "_arxiv_pdf_path": "/some/path.pdf",
            "_arxiv_pdf_pages": 10,
        }
        result = await execute({"start_page": "abc", "end_page": "def"}, ctx)
        assert "整数" in result


# ---------------------------------------------------------------------------
# web_agent callable.json 更新检查
# ---------------------------------------------------------------------------


class TestWebAgentCallable:
    def test_web_agent_allows_new_callers(self) -> None:
        web_agent_callable = (
            Path(__file__).resolve().parent.parent
            / "src"
            / "Undefined"
            / "skills"
            / "agents"
            / "web_agent"
            / "callable.json"
        )
        cfg = json.loads(web_agent_callable.read_text(encoding="utf-8"))
        callers = cfg["allowed_callers"]
        assert "summary_agent" in callers
        assert "arxiv_analysis_agent" in callers
