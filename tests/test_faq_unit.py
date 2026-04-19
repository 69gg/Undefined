"""FAQ 存储管理 单元测试"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from Undefined.faq import FAQ, FAQStorage, extract_faq_title

_WRITE_JSON = "Undefined.utils.io.write_json"
_READ_JSON = "Undefined.utils.io.read_json"
_DELETE_FILE = "Undefined.utils.io.delete_file"


# ---------------------------------------------------------------------------
# FAQ dataclass
# ---------------------------------------------------------------------------


class TestFAQDataclass:
    def _sample(self) -> FAQ:
        return FAQ(
            id="20250101-001",
            group_id=12345,
            target_qq=67890,
            start_time="2025-01-01T00:00:00",
            end_time="2025-01-02T00:00:00",
            created_at="2025-01-01T00:00:00",
            title="测试标题",
            content="测试内容",
        )

    def test_to_dict(self) -> None:
        faq = self._sample()
        d = faq.to_dict()
        assert d["id"] == "20250101-001"
        assert d["group_id"] == 12345
        assert d["title"] == "测试标题"

    def test_from_dict(self) -> None:
        faq = self._sample()
        d = faq.to_dict()
        restored = FAQ.from_dict(d)
        assert restored == faq

    def test_roundtrip(self) -> None:
        faq = self._sample()
        assert FAQ.from_dict(faq.to_dict()) == faq


# ---------------------------------------------------------------------------
# extract_faq_title
# ---------------------------------------------------------------------------


class TestExtractFaqTitle:
    def test_extract_from_question_colon(self) -> None:
        content = "**问题**: 如何重启服务？\n回答是这样的"
        assert extract_faq_title(content) == "如何重启服务？"

    def test_extract_from_question_chinese_colon(self) -> None:
        content = "**问题**：如何重启服务？\n回答是这样的"
        assert extract_faq_title(content) == "如何重启服务？"

    def test_extract_truncates_long_title(self) -> None:
        long_question = "x" * 200
        content = f"**问题**: {long_question}"
        result = extract_faq_title(content)
        assert len(result) <= 100

    def test_extract_from_bug_section(self) -> None:
        content = "## Bug 问题描述\n登录页面崩溃\n更多细节"
        assert extract_faq_title(content) == "登录页面崩溃"

    def test_extract_bug_section_truncates(self) -> None:
        long_desc = "y" * 200
        content = f"## Bug 问题描述\n{long_desc}"
        result = extract_faq_title(content)
        assert len(result) <= 100

    def test_extract_bug_section_skips_heading(self) -> None:
        content = "## Bug 问题描述\n# 子标题\n实际描述"
        assert extract_faq_title(content) == "实际描述"

    def test_extract_no_match_returns_default(self) -> None:
        content = "一段普通文本"
        assert extract_faq_title(content) == "未命名问题"

    def test_extract_empty_content(self) -> None:
        assert extract_faq_title("") == "未命名问题"

    def test_question_priority_over_bug(self) -> None:
        content = "**问题**: 优先问题\n## Bug 问题描述\nbug 内容"
        assert extract_faq_title(content) == "优先问题"


# ---------------------------------------------------------------------------
# FAQStorage
# ---------------------------------------------------------------------------


class TestFAQStorage:
    def _make_storage(self) -> FAQStorage:
        with patch.object(Path, "mkdir"):
            return FAQStorage(base_dir="data/faq")

    @pytest.mark.asyncio
    async def test_create(self) -> None:
        storage = self._make_storage()
        with (
            patch.object(Path, "mkdir"),
            patch.object(Path, "glob", return_value=[]),
            patch(_WRITE_JSON, new_callable=AsyncMock),
        ):
            faq = await storage.create(
                group_id=100,
                target_qq=200,
                start_time="2025-01-01",
                end_time="2025-01-02",
                title="标题",
                content="内容",
            )
        assert faq.group_id == 100
        assert faq.title == "标题"
        assert faq.id  # 有生成 ID

    @pytest.mark.asyncio
    async def test_get_existing(self) -> None:
        storage = self._make_storage()
        sample = FAQ(
            id="20250101-001",
            group_id=100,
            target_qq=200,
            start_time="s",
            end_time="e",
            created_at="c",
            title="t",
            content="body",
        )
        with (
            patch.object(Path, "mkdir"),
            patch(_READ_JSON, new_callable=AsyncMock, return_value=sample.to_dict()),
        ):
            result = await storage.get(100, "20250101-001")
        assert result is not None
        assert result.title == "t"

    @pytest.mark.asyncio
    async def test_get_nonexistent(self) -> None:
        storage = self._make_storage()
        with (
            patch.object(Path, "mkdir"),
            patch(_READ_JSON, new_callable=AsyncMock, return_value=None),
        ):
            result = await storage.get(100, "nonexist")
        assert result is None

    @pytest.mark.asyncio
    async def test_list_all(self) -> None:
        storage = self._make_storage()
        faq1 = FAQ(
            id="001",
            group_id=1,
            target_qq=2,
            start_time="s",
            end_time="e",
            created_at="c",
            title="t1",
            content="c1",
        )
        faq2 = FAQ(
            id="002",
            group_id=1,
            target_qq=2,
            start_time="s",
            end_time="e",
            created_at="c",
            title="t2",
            content="c2",
        )
        mock_files = [Path("a.json"), Path("b.json")]
        results_iter = iter([faq1.to_dict(), faq2.to_dict()])

        with (
            patch.object(Path, "mkdir"),
            patch.object(Path, "glob", return_value=mock_files),
            patch(
                _READ_JSON,
                new_callable=AsyncMock,
                side_effect=lambda *a, **kw: next(results_iter),
            ),
        ):
            faqs = await storage.list_all(1)

        assert len(faqs) == 2

    @pytest.mark.asyncio
    async def test_search_matches(self) -> None:
        storage = self._make_storage()
        faq_match = FAQ(
            id="001",
            group_id=1,
            target_qq=2,
            start_time="s",
            end_time="e",
            created_at="c",
            title="Python 教程",
            content="内容",
        )
        faq_no_match = FAQ(
            id="002",
            group_id=1,
            target_qq=2,
            start_time="s",
            end_time="e",
            created_at="c",
            title="其他",
            content="其他内容",
        )
        mock_files = [Path("a.json"), Path("b.json")]
        results_iter = iter([faq_match.to_dict(), faq_no_match.to_dict()])

        with (
            patch.object(Path, "mkdir"),
            patch.object(Path, "glob", return_value=mock_files),
            patch(
                _READ_JSON,
                new_callable=AsyncMock,
                side_effect=lambda *a, **kw: next(results_iter),
            ),
        ):
            results = await storage.search(1, "python")

        assert len(results) == 1
        assert results[0].title == "Python 教程"

    @pytest.mark.asyncio
    async def test_search_case_insensitive(self) -> None:
        storage = self._make_storage()
        faq = FAQ(
            id="001",
            group_id=1,
            target_qq=2,
            start_time="s",
            end_time="e",
            created_at="c",
            title="UPPER",
            content="body",
        )
        mock_files = [MagicMock(spec=Path)]

        with (
            patch.object(Path, "mkdir"),
            patch.object(Path, "glob", return_value=mock_files),
            patch(_READ_JSON, new_callable=AsyncMock, return_value=faq.to_dict()),
        ):
            results = await storage.search(1, "upper")

        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_search_in_content(self) -> None:
        storage = self._make_storage()
        faq = FAQ(
            id="001",
            group_id=1,
            target_qq=2,
            start_time="s",
            end_time="e",
            created_at="c",
            title="无关标题",
            content="详细的 Python 教程",
        )
        mock_files = [MagicMock(spec=Path)]

        with (
            patch.object(Path, "mkdir"),
            patch.object(Path, "glob", return_value=mock_files),
            patch(_READ_JSON, new_callable=AsyncMock, return_value=faq.to_dict()),
        ):
            results = await storage.search(1, "python")

        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_delete(self) -> None:
        storage = self._make_storage()
        with (
            patch.object(Path, "mkdir"),
            patch(_DELETE_FILE, new_callable=AsyncMock, return_value=True),
        ):
            result = await storage.delete(100, "20250101-001")
        assert result is True

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self) -> None:
        storage = self._make_storage()
        with (
            patch.object(Path, "mkdir"),
            patch(_DELETE_FILE, new_callable=AsyncMock, return_value=False),
        ):
            result = await storage.delete(100, "nonexist")
        assert result is False
