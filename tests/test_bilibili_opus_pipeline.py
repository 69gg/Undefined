from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

from Undefined.handlers import MessageHandler
from Undefined.skills.pipelines import PipelineRegistry
from Undefined.utils.message_targets import DeliveryAddress
from Undefined.utils.sender import AddressBoundSender


def _handler(config: Any) -> Any:
    handler: Any = MessageHandler.__new__(MessageHandler)
    handler.config = config
    handler.sender = SimpleNamespace()
    handler.onebot = SimpleNamespace()
    handler._extract_bilibili_ids = AsyncMock(return_value=[])
    handler._extract_bilibili_opus_ids = AsyncMock(return_value=[])
    handler._extract_douyin_ids = AsyncMock(return_value=[])
    handler._extract_arxiv_ids = AsyncMock(return_value=[])
    handler._extract_github_repo_ids = AsyncMock(return_value=[])
    handler._handle_bilibili_extract = AsyncMock()
    handler._handle_bilibili_opus_extract = AsyncMock()
    handler._handle_douyin_extract = AsyncMock()
    handler._handle_arxiv_extract = AsyncMock()
    handler._handle_github_extract = AsyncMock()
    handler.pipeline_registry = PipelineRegistry()
    handler.pipeline_registry.load_items()
    return handler


def _config(**overrides: Any) -> Any:
    base: dict[str, Any] = {
        "bilibili_auto_extract_enabled": True,
        "bilibili_opus_enabled": True,
        "bilibili_opus_max_items": 3,
        "bilibili_cookie": "",
        "is_bilibili_auto_extract_allowed_group": lambda _gid: True,
        "is_bilibili_auto_extract_allowed_private": lambda _uid: True,
        "douyin_auto_extract_enabled": False,
        "arxiv_auto_extract_enabled": False,
        "github_auto_extract_enabled": False,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


@pytest.mark.asyncio
async def test_bilibili_opus_pipeline_dispatches_to_handler() -> None:
    handler = _handler(_config())
    handler._extract_bilibili_opus_ids = AsyncMock(return_value=["933099353259638816"])

    handled = await handler._run_pipelines(
        target_id=20001,
        target_type="private",
        text="看看 https://www.bilibili.com/opus/933099353259638816",
        message_content=[],
    )

    assert handled is True
    handler._handle_bilibili_opus_extract.assert_awaited_once_with(
        20001,
        ["933099353259638816"],
        "private",
    )
    handler._handle_bilibili_extract.assert_not_awaited()


@pytest.mark.asyncio
async def test_bilibili_opus_pipeline_skips_when_disabled() -> None:
    handler = _handler(_config(bilibili_opus_enabled=False))
    handler._extract_bilibili_opus_ids = AsyncMock(return_value=["933099353259638816"])

    handled = await handler._run_pipelines(
        target_id=20001,
        target_type="private",
        text="https://www.bilibili.com/opus/933099353259638816",
        message_content=[],
    )

    assert handled is False
    handler._extract_bilibili_opus_ids.assert_not_awaited()
    handler._handle_bilibili_opus_extract.assert_not_awaited()


@pytest.mark.asyncio
async def test_bilibili_opus_pipeline_skips_when_master_switch_off() -> None:
    handler = _handler(_config(bilibili_auto_extract_enabled=False))
    handler._extract_bilibili_opus_ids = AsyncMock(return_value=["933099353259638816"])

    handled = await handler._run_pipelines(
        target_id=20001,
        target_type="private",
        text="https://www.bilibili.com/opus/933099353259638816",
        message_content=[],
    )

    assert handled is False
    handler._extract_bilibili_opus_ids.assert_not_awaited()


@pytest.mark.asyncio
async def test_bilibili_opus_pipeline_respects_allowlist() -> None:
    handler = _handler(
        _config(is_bilibili_auto_extract_allowed_private=lambda _uid: False)
    )
    handler._extract_bilibili_opus_ids = AsyncMock(return_value=["933099353259638816"])

    handled = await handler._run_pipelines(
        target_id=20001,
        target_type="private",
        text="https://www.bilibili.com/opus/933099353259638816",
        message_content=[],
    )

    assert handled is False
    handler._extract_bilibili_opus_ids.assert_not_awaited()


@pytest.mark.asyncio
async def test_bilibili_opus_pipeline_binds_address_sender() -> None:
    handler = _handler(_config())
    handler._extract_bilibili_opus_ids = AsyncMock(return_value=["933099353259638816"])

    await handler._run_pipelines(
        target_id=20001,
        target_type="private",
        text="https://www.bilibili.com/opus/933099353259638816",
        message_content=[],
        address=DeliveryAddress("wechat", 20001),
    )

    args = handler._handle_bilibili_opus_extract.await_args.args
    assert args[:3] == (20001, ["933099353259638816"], "private")
    assert isinstance(args[3], AddressBoundSender)


def _dummy_mixin(config: Any) -> Any:
    """构造一个只带 mixin 所需属性的轻量宿主（mixin 只依赖 config/sender/onebot）。"""
    return SimpleNamespace(
        config=config,
        sender=SimpleNamespace(
            send_group_message=AsyncMock(),
            send_private_message=AsyncMock(),
        ),
        onebot=SimpleNamespace(),
    )


@pytest.mark.asyncio
async def test_bilibili_opus_handler_respects_max_items(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import Undefined.bilibili.opus_sender as opus_sender
    from Undefined.handlers.auto_extract import AutoExtractMixin

    send = AsyncMock(return_value="ok")
    monkeypatch.setattr(opus_sender, "send_opus", send)

    await AutoExtractMixin._handle_bilibili_opus_extract(
        _dummy_mixin(_config(bilibili_opus_max_items=2)),
        20001,
        ["1", "2", "3", "4"],
        "private",
    )

    assert send.await_count == 2
    assert [call.args[0] for call in send.await_args_list] == ["1", "2"]


@pytest.mark.asyncio
async def test_bilibili_opus_handler_reports_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import Undefined.bilibili.opus_sender as opus_sender
    from Undefined.handlers.auto_extract import AutoExtractMixin

    monkeypatch.setattr(
        opus_sender, "send_opus", AsyncMock(side_effect=RuntimeError("boom"))
    )

    dummy = _dummy_mixin(_config())
    await AutoExtractMixin._handle_bilibili_opus_extract(dummy, 20001, ["1"], "private")

    sender_mock = cast(Any, dummy.sender)
    sender_mock.send_private_message.assert_awaited_once()
    assert "图文提取失败" in sender_mock.send_private_message.await_args.args[1]
