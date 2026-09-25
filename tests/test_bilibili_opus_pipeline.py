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


@pytest.mark.asyncio
async def test_detect_passes_item_budget_to_extractor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """检测阶段就把发送预算交给提取器，超出的短链不再解析。"""
    # 管线 handler 按目录动态加载，不是可 import 的包模块
    registry = PipelineRegistry()
    registry.load_items()
    detect = registry._items["bilibili_opus"].detect

    extractor = AsyncMock(return_value=["1", "2", "3", "4", "5"])
    detection = await detect(
        {
            "config": _config(bilibili_opus_max_items=2),
            "target_id": 20001,
            "target_type": "private",
            "text": "https://www.bilibili.com/opus/1",
            "message_content": [],
            "extract_bilibili_opus_ids": extractor,
        }
    )

    assert detection is not None
    assert detection.items == ("1", "2")
    extractor.assert_awaited_once()
    call = extractor.await_args
    assert call is not None
    assert call.kwargs["limit"] == 2


@pytest.mark.asyncio
async def test_mixin_extracts_text_and_share_card_together(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """正文里有图文链接、卡片里是另一篇图文时，两篇都要处理。"""
    import Undefined.bilibili.opus_parser as opus_parser
    from Undefined.handlers.auto_extract import AutoExtractMixin

    monkeypatch.setattr(
        opus_parser,
        "extract_opus_ids_with_shortlinks",
        AsyncMock(return_value=["111"]),
    )
    monkeypatch.setattr(
        opus_parser,
        "extract_opus_from_json_message",
        AsyncMock(return_value=["222", "111"]),
    )

    dummy = cast(Any, SimpleNamespace())
    opus_ids = await AutoExtractMixin._extract_bilibili_opus_ids(
        dummy,
        "https://www.bilibili.com/opus/111",
        [{"type": "json", "data": {"data": "{}"}}],
    )

    assert opus_ids == ["111", "222"]


@pytest.mark.asyncio
async def test_mixin_skips_card_lookup_when_budget_full(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import Undefined.bilibili.opus_parser as opus_parser
    from Undefined.handlers.auto_extract import AutoExtractMixin

    monkeypatch.setattr(
        opus_parser,
        "extract_opus_ids_with_shortlinks",
        AsyncMock(return_value=["111", "222"]),
    )
    card_lookup = AsyncMock(return_value=["333"])
    monkeypatch.setattr(opus_parser, "extract_opus_from_json_message", card_lookup)

    dummy = cast(Any, SimpleNamespace())
    opus_ids = await AutoExtractMixin._extract_bilibili_opus_ids(
        dummy, "text", [], limit=2
    )

    assert opus_ids == ["111", "222"]
    card_lookup.assert_not_awaited()


@pytest.mark.asyncio
async def test_duplicate_card_does_not_consume_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """卡片里的重复图文不能吃掉名额，否则卡片中的新图文会被漏掉。"""
    import Undefined.bilibili.opus_parser as opus_parser
    from Undefined.handlers.auto_extract import AutoExtractMixin

    async def _resolve(url: str) -> str:
        suffix = "111" if url.endswith("dup") else "222"
        return f"https://www.bilibili.com/opus/{suffix}"

    monkeypatch.setattr(
        opus_parser, "resolve_short_url", AsyncMock(side_effect=_resolve)
    )

    def _card(url: str) -> dict[str, Any]:
        import html
        import json

        payload = {"meta": {"detail_1": {"qqdocurl": url}}}
        return {"type": "json", "data": {"data": html.escape(json.dumps(payload))}}

    dummy = cast(Any, SimpleNamespace())
    text = "https://www.bilibili.com/opus/111 https://b23.tv/dup"
    segments = [_card("https://b23.tv/dup"), _card("https://b23.tv/new")]

    # 正文已命中 111，卡片给出重复的 111 + 新的 222；预算 2 应拿到两个 ID
    assert await AutoExtractMixin._extract_bilibili_opus_ids(
        dummy, text, segments, limit=2
    ) == ["111", "222"]
    # 预算 1 时正文已占满，卡片不再贡献
    assert await AutoExtractMixin._extract_bilibili_opus_ids(
        dummy, text, segments, limit=1
    ) == ["111"]
