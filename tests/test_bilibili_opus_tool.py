from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

import Undefined.bilibili.opus_parser as opus_parser
import Undefined.bilibili.opus_sender as opus_sender
import Undefined.skills.tools.bilibili_opus.handler as handler_module
from Undefined.bilibili.models import (
    ImageBlock,
    OpusAuthor,
    OpusCardBlock,
    OpusInfo,
    OpusStats,
    TextBlock,
)
from Undefined.bilibili.opus_sender import (
    fetch_bilibili_opus_attachment,
    format_opus_uid_message,
)
from Undefined.skills.tools.bilibili_opus.handler import execute


def _info(*blocks: Any, **overrides: Any) -> OpusInfo:
    payload: dict[str, Any] = {
        "opus_id": "933099353259638816",
        "title": "测试图文",
        "blocks": tuple(blocks) or (TextBlock("正文"),),
        "author": OpusAuthor(mid=1, name="测试UP"),
        "stats": OpusStats(view=12345, like=88, comment=42, repost=3),
        "pub_ts": 1700000000,
        "cover_url": "https://i0.hdslb.com/cover.jpg",
    }
    payload.update(overrides)
    return OpusInfo(**payload)


def _context(**overrides: Any) -> dict[str, Any]:
    config = SimpleNamespace(bilibili_cookie="SESSDATA=xxx")
    context: dict[str, Any] = {
        "runtime_config": config,
        "sender": SimpleNamespace(
            send_group_message=AsyncMock(),
            send_private_message=AsyncMock(),
        ),
        "onebot": SimpleNamespace(),
        "group_id": 10001,
        "request_type": "group",
        "attachment_registry": SimpleNamespace(register_remote_url=AsyncMock()),
        "scope_key": "group:10001",
    }
    context.update(overrides)
    return context


# ---------- output_mode=info ----------


@pytest.mark.asyncio
async def test_info_mode_returns_summary_without_sending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        opus_sender, "_fetch_opus_info", AsyncMock(return_value=_info())
    )
    context = _context()

    result = await execute(
        {"opus_id": "933099353259638816", "output_mode": "info"}, context
    )

    assert "「测试图文」" in result
    assert "图文 ID: 933099353259638816" in result
    assert "数据: 阅读 1.2万" in result
    assert result.endswith("https://www.bilibili.com/opus/933099353259638816")
    context["sender"].send_group_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_opus_id_accepts_url_and_dynamic_url() -> None:
    for raw in (
        "https://www.bilibili.com/opus/933099353259638816?suffix=1",
        "https://t.bilibili.com/933099353259638816",
        "m.bilibili.com/opus/933099353259638816",
        "933099353259638816",
    ):
        assert await _normalized(raw) == "933099353259638816"


async def _normalized(raw: str) -> str | None:
    from Undefined.skills.tools.bilibili_opus.handler import _normalize_opus_id

    return await _normalize_opus_id(raw)


@pytest.mark.asyncio
async def test_opus_id_resolves_short_link(monkeypatch: pytest.MonkeyPatch) -> None:
    import Undefined.skills.tools.bilibili_opus.handler as handler

    monkeypatch.setattr(
        handler,
        "resolve_short_url",
        AsyncMock(return_value="https://www.bilibili.com/opus/555555555555555"),
    )
    assert await _normalized("https://b23.tv/abcd123") == "555555555555555"


@pytest.mark.asyncio
async def test_unparsable_opus_id_reports_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fetch = AsyncMock(return_value=_info())
    monkeypatch.setattr(opus_sender, "_fetch_opus_info", fetch)

    result = await execute({"opus_id": "https://example.com/not-opus"}, _context())

    assert result.startswith("无法解析图文标识")
    fetch.assert_not_awaited()


@pytest.mark.asyncio
async def test_empty_opus_id_and_bad_mode() -> None:
    assert await execute({"opus_id": "  "}, _context()) == "opus_id 不能为空"
    assert (
        await execute({"opus_id": "1", "output_mode": "bogus"}, _context())
        == "output_mode 只能是 send、uid、info 或 text"
    )


# ---------- output_mode=uid ----------


@pytest.mark.asyncio
async def test_uid_mode_registers_images(monkeypatch: pytest.MonkeyPatch) -> None:
    info = _info(
        TextBlock("正文"),
        ImageBlock(("https://i0.hdslb.com/1.jpg", "https://i0.hdslb.com/2.jpg")),
    )
    monkeypatch.setattr(opus_sender, "_fetch_opus_info", AsyncMock(return_value=info))
    registry = SimpleNamespace(
        register_remote_url=AsyncMock(
            side_effect=[
                SimpleNamespace(uid="pic_aaa"),
                SimpleNamespace(uid="pic_bbb"),
            ]
        )
    )
    context = _context(attachment_registry=registry)

    result = await execute(
        {"opus_id": "933099353259638816", "output_mode": "uid"}, context
    )

    assert '图片 1: <attachment uid="pic_aaa"/>' in result
    assert '图片 2: <attachment uid="pic_bbb"/>' in result
    assert "图片: 已登记 2/2 张" in result
    assert registry.register_remote_url.await_count == 2
    first = registry.register_remote_url.await_args_list[0]
    assert first.args == ("group:10001", "https://i0.hdslb.com/1.jpg")
    assert first.kwargs["kind"] == "image"
    assert first.kwargs["source_kind"] == "bilibili_opus"


@pytest.mark.asyncio
async def test_uid_mode_respects_max_images_and_reports_truncation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    info = _info(
        ImageBlock(tuple(f"https://i0.hdslb.com/{index}.jpg" for index in range(1, 5)))
    )
    monkeypatch.setattr(opus_sender, "_fetch_opus_info", AsyncMock(return_value=info))
    registry = SimpleNamespace(
        register_remote_url=AsyncMock(
            side_effect=[SimpleNamespace(uid=f"pic_{index}") for index in range(1, 5)]
        )
    )

    result = await execute(
        {"opus_id": "1", "output_mode": "uid", "max_images": 2},
        _context(attachment_registry=registry),
    )

    assert registry.register_remote_url.await_count == 2
    assert "图片: 已登记 2/4 张" in result
    assert "仅登记前 2 张图片" in result


@pytest.mark.asyncio
async def test_uid_mode_keeps_going_after_one_image_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    info = _info(
        ImageBlock(("https://i0.hdslb.com/1.jpg", "https://i0.hdslb.com/2.jpg"))
    )
    monkeypatch.setattr(opus_sender, "_fetch_opus_info", AsyncMock(return_value=info))
    registry = SimpleNamespace(
        register_remote_url=AsyncMock(
            side_effect=[RuntimeError("下载失败"), SimpleNamespace(uid="pic_ok")]
        )
    )

    result = await execute(
        {"opus_id": "1", "output_mode": "uid"},
        _context(attachment_registry=registry),
    )

    assert '图片 1: <attachment uid="pic_ok"/>' in result
    assert "图片登记失败" in result
    assert "下载失败" in result


@pytest.mark.asyncio
async def test_uid_mode_reports_missing_components(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fetch = AsyncMock(return_value=_info(ImageBlock(("https://i0.hdslb.com/1.jpg",))))
    monkeypatch.setattr(opus_sender, "_fetch_opus_info", fetch)

    no_registry = _context(attachment_registry=None)
    assert "缺少必要的运行时组件" in await execute(
        {"opus_id": "1", "output_mode": "uid"}, no_registry
    )

    # scope_key 为空时先尝试 scope_from_context 兜底，兜底也失败才报错
    no_scope = _context(scope_key="", group_id=None, request_type=None, user_id=None)
    assert "无法确定附件作用域" in await execute(
        {"opus_id": "1", "output_mode": "uid"}, no_scope
    )
    fetch.assert_not_awaited()


@pytest.mark.asyncio
async def test_uid_mode_reports_no_images(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        opus_sender,
        "_fetch_opus_info",
        AsyncMock(return_value=_info(TextBlock("只有文字"))),
    )
    registry = SimpleNamespace(register_remote_url=AsyncMock())

    result = await execute(
        {"opus_id": "1", "output_mode": "uid"},
        _context(attachment_registry=registry),
    )

    assert "没有可登记的图片" in result
    registry.register_remote_url.assert_not_awaited()


# ---------- output_mode=send ----------


@pytest.mark.asyncio
async def test_send_mode_uses_resolved_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    send = AsyncMock(return_value="已发送 Bilibili 图文合并转发「测试图文」")
    # 工具从 opus_sender 导入函数本体，需 patch 工具模块里的绑定
    monkeypatch.setattr(handler_module, "send_opus", send)

    result = await execute(
        {"opus_id": "1", "target_type": "private", "target_id": 7}, _context()
    )

    assert result.startswith("已发送 Bilibili 图文合并转发")
    send.assert_awaited_once()
    call = send.await_args
    assert call is not None
    assert call.args[0] == "1"
    assert call.kwargs["target_type"] == "private"
    assert call.kwargs["target_id"] == 7
    assert call.kwargs["cookie"] == "SESSDATA=xxx"


@pytest.mark.asyncio
async def test_send_mode_requires_target() -> None:
    context = _context()
    context.pop("group_id")
    context.pop("request_type")

    result = await execute({"opus_id": "1"}, context)

    assert result.startswith("目标解析失败")


@pytest.mark.asyncio
async def test_send_mode_requires_sender_and_onebot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(opus_sender, "send_opus", AsyncMock())
    context = _context(sender=None)

    result = await execute({"opus_id": "1"}, context)

    assert "缺少必要的运行时组件" in result


# ---------- 附件模式辅助 ----------


def test_format_opus_uid_message_lists_uids_and_failures() -> None:
    message = format_opus_uid_message(
        _info(),
        uids=["pic_1", "pic_2"],
        image_total=3,
        failures=["#3 boom"],
    )

    assert '图片 1: <attachment uid="pic_1"/>' in message
    assert '图片 2: <attachment uid="pic_2"/>' in message
    assert "图片: 已登记 2/3 张" in message
    assert "图片登记失败: #3 boom" in message


@pytest.mark.asyncio
async def test_fetch_attachment_clamps_max_images(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    info = _info(
        ImageBlock(("https://i0.hdslb.com/1.jpg", "https://i0.hdslb.com/2.jpg"))
    )
    monkeypatch.setattr(opus_sender, "_fetch_opus_info", AsyncMock(return_value=info))
    registry = SimpleNamespace(
        register_remote_url=AsyncMock(
            side_effect=[SimpleNamespace(uid="pic_1"), SimpleNamespace(uid="pic_2")]
        )
    )

    result = await fetch_bilibili_opus_attachment(
        "1",
        attachment_registry=registry,
        scope_key="group:1",
        max_images=0,
    )

    # max_images<=0 收敛为 1 张，避免返回空结果
    assert registry.register_remote_url.await_count == 1
    assert "已登记 1/2 张" in result


@pytest.mark.asyncio
async def test_fetch_attachment_validates_inputs() -> None:
    registry = SimpleNamespace(register_remote_url=AsyncMock())
    assert (
        await fetch_bilibili_opus_attachment(
            " ", attachment_registry=registry, scope_key="group:1"
        )
        == "图文 ID 不能为空"
    )
    assert "缺少必要的运行时组件" in await fetch_bilibili_opus_attachment(
        "1", attachment_registry=None, scope_key="group:1"
    )
    assert "无法确定附件作用域" in await fetch_bilibili_opus_attachment(
        "1", attachment_registry=registry, scope_key=" "
    )


@pytest.mark.asyncio
async def test_normalize_opus_id_ignores_unrelated_text() -> None:
    from Undefined.skills.tools.bilibili_opus.handler import _normalize_opus_id

    assert await _normalize_opus_id("BV1xx411c7mD") is None
    assert (
        await _normalize_opus_id("https://www.bilibili.com/video/BV1xx411c7mD") is None
    )


@pytest.mark.asyncio
async def test_opus_card_block_does_not_break_attachment_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """uid 模式只关心图片；正文里的嵌套卡片不应触发额外请求。"""
    info = _info(
        TextBlock("正文"),
        OpusCardBlock(opus_id="999", title="嵌套"),
        ImageBlock(("https://i0.hdslb.com/1.jpg",)),
    )
    fetch = AsyncMock(return_value=info)
    monkeypatch.setattr(opus_sender, "_fetch_opus_info", fetch)
    registry = SimpleNamespace(
        register_remote_url=AsyncMock(return_value=SimpleNamespace(uid="pic_1"))
    )

    result = await fetch_bilibili_opus_attachment(
        "1", attachment_registry=registry, scope_key="group:1"
    )

    assert fetch.await_count == 1
    assert "已登记 1/1 张" in result


def test_opus_parser_patterns_are_reused_by_tool() -> None:
    """工具复用管线同一套正则，避免两处漂移。"""
    assert opus_parser.OPUS_URL_PATTERN.search("bilibili.com/opus/123456") is not None
    assert (
        opus_parser.DYNAMIC_ID_URL_PATTERN.search("t.bilibili.com/123456") is not None
    )


# ---------- output_mode=text ----------


def _long_info(body: str) -> OpusInfo:
    return _info(TextBlock(body), title="长文图文")


@pytest.mark.asyncio
async def test_text_mode_defaults_to_first_1000_chars(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        opus_sender, "_fetch_opus_info", AsyncMock(return_value=_long_info("甲" * 2500))
    )

    result = await execute({"opus_id": "1", "output_mode": "text"}, _context())

    assert "正文共 2500 字，本次返回 0-1000 字" in result
    assert "可用 start=1000 继续读取" in result
    assert "甲" * 1000 in result
    assert "甲" * 1001 not in result


@pytest.mark.asyncio
async def test_text_mode_start_and_end(monkeypatch: pytest.MonkeyPatch) -> None:
    body = "".join(str(index % 10) for index in range(500))
    monkeypatch.setattr(
        opus_sender, "_fetch_opus_info", AsyncMock(return_value=_long_info(body))
    )

    result = await execute(
        {"opus_id": "1", "output_mode": "text", "start": 120, "end": 130}, _context()
    )

    assert "本次返回 120-130 字" in result
    assert "0123456789" in result


@pytest.mark.asyncio
async def test_text_mode_keyword_query(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        opus_sender,
        "_fetch_opus_info",
        AsyncMock(return_value=_long_info("甲" * 200 + "目标词" + "乙" * 200)),
    )

    result = await execute(
        {"opus_id": "1", "output_mode": "text", "keyword": "目标词"}, _context()
    )

    assert "关键词「目标词」命中位置: 140-263" in result
    assert "目标词" in result


@pytest.mark.asyncio
async def test_text_mode_keyword_miss(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        opus_sender, "_fetch_opus_info", AsyncMock(return_value=_long_info("甲" * 100))
    )

    result = await execute(
        {"opus_id": "1", "output_mode": "text", "keyword": "没有这个词"}, _context()
    )

    assert "在正文中没有命中" in result


@pytest.mark.asyncio
async def test_text_mode_invalid_arguments(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        opus_sender, "_fetch_opus_info", AsyncMock(return_value=_long_info("甲" * 100))
    )
    context = _context()

    assert await execute(
        {"opus_id": "1", "output_mode": "text", "start": "abc"}, context
    ) == ("start 必须是整数")
    assert await execute(
        {"opus_id": "1", "output_mode": "text", "limit": 0}, context
    ) == ("limit 必须大于 0")
    assert await execute(
        {"opus_id": "1", "output_mode": "text", "limit": 99999}, context
    ) == ("limit 过大（99999，上限 20000）")
    assert await execute(
        {"opus_id": "1", "output_mode": "text", "keyword": "短"}, context
    ) == ("keyword 至少 2 个字，过短会命中大量无关位置")


@pytest.mark.asyncio
async def test_text_mode_does_not_send_or_register(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        opus_sender, "_fetch_opus_info", AsyncMock(return_value=_long_info("甲" * 50))
    )
    context = _context()

    await execute({"opus_id": "1", "output_mode": "text"}, context)

    context["sender"].send_group_message.assert_not_awaited()
    context["attachment_registry"].register_remote_url.assert_not_awaited()


@pytest.mark.asyncio
async def test_text_mode_reports_empty_body(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        opus_sender,
        "_fetch_opus_info",
        AsyncMock(return_value=_info(TextBlock(""), title="空")),
    )

    result = await execute({"opus_id": "1", "output_mode": "text"}, _context())

    assert "（该图文没有正文文字）" in result
