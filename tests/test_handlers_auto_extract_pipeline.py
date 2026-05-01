from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from Undefined.handlers import MessageHandler
from Undefined.skills.auto_pipeline import AutoPipelineRegistry


@pytest.mark.asyncio
async def test_auto_extract_pipeline_processes_all_matches() -> None:
    handler: Any = MessageHandler.__new__(MessageHandler)
    handler.sender = SimpleNamespace()
    handler.onebot = SimpleNamespace()
    handler.config = SimpleNamespace(
        bilibili_auto_extract_enabled=True,
        is_bilibili_auto_extract_allowed_private=lambda _uid: True,
        arxiv_auto_extract_enabled=True,
        is_arxiv_auto_extract_allowed_private=lambda _uid: True,
        github_auto_extract_enabled=True,
        is_github_auto_extract_allowed_private=lambda _uid: True,
    )
    handler._extract_bilibili_ids = AsyncMock(return_value=["BV1xx411c7mD"])
    handler._extract_arxiv_ids = MagicMock(return_value=["2501.01234"])
    handler._extract_github_repo_ids = MagicMock(return_value=["69gg/Undefined"])
    handler._handle_bilibili_extract = AsyncMock()
    handler._handle_arxiv_extract = AsyncMock()
    handler._handle_github_extract = AsyncMock()
    handler.auto_pipeline_registry = AutoPipelineRegistry()
    handler.auto_pipeline_registry.load_items()

    handled = await handler._run_auto_extract_pipeline(
        target_id=20001,
        target_type="private",
        text="BV1xx411c7mD 69gg/Undefined",
        message_content=[],
    )

    assert handled is True
    handler._handle_bilibili_extract.assert_awaited_once_with(
        20001,
        ["BV1xx411c7mD"],
        "private",
    )
    handler._handle_arxiv_extract.assert_awaited_once_with(
        20001,
        ["2501.01234"],
        "private",
    )
    handler._handle_github_extract.assert_awaited_once_with(
        20001,
        ["69gg/Undefined"],
        "private",
    )
