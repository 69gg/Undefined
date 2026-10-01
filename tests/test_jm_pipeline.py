from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from Undefined.handlers import MessageHandler
from Undefined.skills.pipelines import PipelineRegistry


def _handler(config: Any) -> Any:
    handler: Any = MessageHandler.__new__(MessageHandler)
    handler.config = config
    handler.sender = SimpleNamespace()
    handler.onebot = SimpleNamespace()
    handler._extract_jm_ids = MagicMock(return_value=[])
    handler._handle_jm_extract = AsyncMock()
    handler.pipeline_registry = PipelineRegistry()
    handler.pipeline_registry.load_items()
    return handler


def _config(**overrides: Any) -> Any:
    base: dict[str, Any] = {
        "bilibili_auto_extract_enabled": False,
        "bilibili_opus_enabled": False,
        "douyin_auto_extract_enabled": False,
        "arxiv_auto_extract_enabled": False,
        "github_auto_extract_enabled": False,
        "jm_auto_extract_enabled": True,
        "is_jm_auto_extract_allowed_group": lambda _gid: True,
        "is_jm_auto_extract_allowed_private": lambda _uid: True,
        "jm_auto_extract_max_items": 1,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


@pytest.mark.asyncio
async def test_jm_pipeline_dispatches_to_handler() -> None:
    handler = _handler(_config())
    handler._extract_jm_ids = MagicMock(return_value=["1114751"])

    handled = await handler._run_pipelines(
        target_id=20001,
        target_type="private",
        text="jm1114751",
        message_content=[],
    )

    assert handled is True
    handler._extract_jm_ids.assert_called_once()
    handler._handle_jm_extract.assert_awaited_once_with(20001, ["1114751"], "private")


@pytest.mark.asyncio
async def test_jm_pipeline_uses_real_extractor_for_text_and_share_card() -> None:
    handler = _handler(_config())
    # 删掉替身，回落到 MessageHandler 上真实的 _extract_jm_ids
    del handler._extract_jm_ids
    card = {"meta": {"detail_1": {"qqdocurl": "https://18comic.vip/album/2222222"}}}

    handled = await handler._run_pipelines(
        target_id=20001,
        target_type="private",
        text="jm1114751",
        message_content=[
            {"type": "text", "data": {"text": "jm1114751"}},
            {"type": "json", "data": {"data": json.dumps(card)}},
        ],
    )

    assert handled is True
    handler._handle_jm_extract.assert_awaited_once_with(
        20001, ["1114751", "2222222"], "private"
    )


@pytest.mark.asyncio
async def test_jm_pipeline_skips_when_disabled() -> None:
    handler = _handler(_config(jm_auto_extract_enabled=False))

    handled = await handler._run_pipelines(
        target_id=20001,
        target_type="private",
        text="jm1114751",
        message_content=[],
    )

    assert handled is False
    handler._extract_jm_ids.assert_not_called()
    handler._handle_jm_extract.assert_not_awaited()


@pytest.mark.asyncio
async def test_jm_pipeline_respects_allowlist() -> None:
    handler = _handler(
        _config(
            is_jm_auto_extract_allowed_group=lambda gid: gid == 123456,
        )
    )

    handled = await handler._run_pipelines(
        target_id=654321,
        target_type="group",
        text="jm1114751",
        message_content=[],
    )

    assert handled is False
    handler._extract_jm_ids.assert_not_called()
