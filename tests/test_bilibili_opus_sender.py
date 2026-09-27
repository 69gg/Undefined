from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

import Undefined.bilibili.opus_sender as opus_sender
from Undefined.bilibili.errors import OpusUnavailableError
from Undefined.bilibili.format import NODE_TEXT_BUDGET
from Undefined.bilibili.models import (
    ImageBlock,
    LinkCardBlock,
    OpusAuthor,
    OpusCardBlock,
    OpusInfo,
    TextBlock,
    VideoCardBlock,
    VideoInfo,
    VideoStats,
)
from Undefined.onebot.client import OneBotDeliveryUncertainError


def _author(name: str = "测试UP") -> OpusAuthor:
    return OpusAuthor(mid=293793435, name=name, avatar_url="https://i0.hdslb.com/a.jpg")


def _info(
    *blocks: Any,
    title: str = "测试图文",
    cover_url: str = "https://i0.hdslb.com/cover.jpg",
    **overrides: Any,
) -> OpusInfo:
    payload: dict[str, Any] = {
        "opus_id": "933099353259638816",
        "title": title,
        "blocks": tuple(blocks) or (TextBlock("正文"),),
        "author": _author(),
        "pub_ts": 1700000000,
        "cover_url": cover_url,
    }
    payload.update(overrides)
    return OpusInfo(**payload)


def _sender() -> Any:
    return SimpleNamespace(
        send_group_forward_message=AsyncMock(),
        send_private_forward_message=AsyncMock(),
    )


def _config(**overrides: Any) -> Any:
    base: dict[str, Any] = {
        "bilibili_opus_nested_depth": 5,
        "bilibili_opus_nested_max_cards": 8,
        "bilibili_prefer_quality": 80,
        "bilibili_max_duration": 600,
        "bilibili_max_file_size": 100,
        "bilibili_oversize_strategy": "downgrade",
        "bilibili_danmaku_enabled": False,
        "bilibili_danmaku_batch_size": 100,
        "bilibili_danmaku_max_count": 0,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


async def _build(info: OpusInfo, *, config: Any = None, **kwargs: Any) -> list[Any]:
    return await opus_sender.build_opus_nodes(
        info,
        sender=_sender(),
        target_type="group",
        target_id=10001,
        config=config if config is not None else _config(),
        **kwargs,
    )


def _segment_types(node: dict[str, Any]) -> list[str]:
    return [segment["type"] for segment in node["data"]["content"]]


def _content_nodes(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """返回正文节点；超预算时正文收进顶层「正文」节点，这里展开一层。"""
    content = nodes[1:]
    if len(content) == 1:
        segments = content[0]["data"]["content"]
        if (
            isinstance(segments, list)
            and segments
            and isinstance(segments[0], dict)
            and segments[0].get("type") == "node"
        ):
            return list(segments)
    return content


def _iter_segments(nodes: list[dict[str, Any]]) -> Iterator[dict[str, Any]]:
    """深度遍历节点里的消息段（嵌套节点视为普通节点继续展开）。"""
    for node in nodes:
        content = node["data"]["content"]
        if not isinstance(content, list):
            continue
        for segment in content:
            if segment.get("type") == "node":
                yield from _iter_segments([segment])
            else:
                yield segment


def _flatten_text(nodes: list[dict[str, Any]]) -> str:
    return "".join(
        str(segment["data"]["text"])
        for segment in _iter_segments(nodes)
        if segment["type"] == "text"
    )


def _preview_chars(nodes: list[dict[str, Any]]) -> int:
    """估算 NapCat packet 卡片 ``news`` 里的文本量：只统计顶层节点直接文本。"""
    total = 0
    for node in nodes:
        content = node["data"]["content"]
        if not isinstance(content, list):
            continue
        total += sum(
            len(str(segment["data"]["text"]))
            for segment in content
            if segment["type"] == "text"
        )
    return total


# ---------- 节点结构 ----------


@pytest.mark.asyncio
async def test_meta_node_is_first_and_content_follows() -> None:
    info = _info(TextBlock("第一段"), ImageBlock(("https://i0.hdslb.com/1.jpg",)))

    nodes = await _build(info)

    assert len(nodes) == 2
    meta, content = nodes
    assert meta["data"]["name"] == "图文信息"
    assert _segment_types(meta) == ["image", "text"]
    meta_text = meta["data"]["content"][1]["data"]["text"]
    assert "「测试图文」" in meta_text
    assert "UP主: 测试UP" in meta_text
    assert "时间: 2023-11-15" in meta_text
    assert "数据: 阅读 0 |" in meta_text
    assert meta_text.endswith("https://www.bilibili.com/opus/933099353259638816")

    assert content["data"]["name"] == "正文"
    assert _segment_types(content) == ["text", "image"]
    assert content["data"]["content"][0]["data"]["text"] == "第一段"
    assert content["data"]["content"][1]["data"]["file"] == "https://i0.hdslb.com/1.jpg"


@pytest.mark.asyncio
async def test_meta_node_omits_cover_when_missing() -> None:
    nodes = await _build(_info(TextBlock("正文"), cover_url=""))
    assert _segment_types(nodes[0]) == ["text"]


@pytest.mark.asyncio
async def test_forward_source_is_rendered_in_meta() -> None:
    info = _info(
        TextBlock("转发正文"),
        is_forward=True,
        forward_origin=_author("原作者"),
    )
    nodes = await _build(info)
    assert "转发自: 原作者" in nodes[0]["data"]["content"][1]["data"]["text"]


@pytest.mark.asyncio
async def test_empty_blocks_still_produce_content_node() -> None:
    nodes = await _build(_info())
    assert len(nodes) == 2
    assert nodes[1]["data"]["content"][0]["data"]["text"] == "正文"


# ---------- 分段 ----------


@pytest.mark.asyncio
async def test_long_text_is_split_and_nothing_is_lost() -> None:
    body = "A" * 9000
    nodes = await _build(_info(TextBlock(body)))

    contents = _content_nodes(nodes)
    assert len(contents) == 8  # 9000 字按 1200 字预算切成 8 个节点
    assert contents[0]["data"]["name"].startswith("正文 1/8")
    assert _flatten_text(_content_nodes(nodes)) == body
    for node in contents:
        assert len(node["data"]["content"][0]["data"]["text"]) <= NODE_TEXT_BUDGET


@pytest.mark.asyncio
async def test_chunking_prefers_newline_boundary() -> None:
    body = "第一行\n" + "B" * 5000
    nodes = await _build(_info(TextBlock(body)))

    assert _content_nodes(nodes)[0]["data"]["content"][0]["data"]["text"] == "第一行\n"


@pytest.mark.asyncio
async def test_images_keep_relative_position_across_chunks() -> None:
    # 8000 字正好切满预算内的若干块，后续图文块落在独立的节点里，便于断言顺序
    long_text = "C" * 8000
    info = _info(
        TextBlock(long_text),
        ImageBlock(("https://i0.hdslb.com/mid.jpg",)),
        TextBlock("结尾"),
    )

    nodes = await _build(info)
    contents = _content_nodes(nodes)

    # 图片保留在原文位置（尾段之前），不会被提前或丢弃
    assert [_segment_types(node) for node in contents] == [
        ["text"],
        ["text"],
        ["text"],
        ["text"],
        ["text"],
        ["text"],
        ["text", "image", "text"],
    ]
    last = contents[-1]["data"]["content"]
    assert last[1]["data"]["file"] == "https://i0.hdslb.com/mid.jpg"
    assert last[2]["data"]["text"] == "结尾"
    assert _flatten_text(_content_nodes(nodes)) == long_text + "结尾"


@pytest.mark.asyncio
async def test_code_block_long_text_is_split_without_loss() -> None:
    code = "```python\n" + "x = 1\n" * 2000 + "```"
    nodes = await _build(_info(TextBlock(code)))
    assert _flatten_text(_content_nodes(nodes)) == code


# ---------- 顶层预览收敛 ----------


@pytest.mark.asyncio
async def test_online_shape_body_is_nested_under_single_node() -> None:
    """线上失败形态回归：107 段共 13589 字 + 20 图不得压进一个顶层节点。"""
    blocks: list[Any] = [TextBlock("x" * 127) for _ in range(107)]
    blocks.extend(
        ImageBlock((f"https://i0.hdslb.com/bfs/new_dyn/{index}.png",))
        for index in range(20)
    )
    body = "x" * 127 * 107

    nodes = await _build(_info(*blocks))

    assert [node["data"]["name"] for node in nodes] == ["图文信息", "正文"]
    assert set(_segment_types(nodes[1])) == {"node"}
    contents = _content_nodes(nodes)
    assert all(
        len(str(segment["data"]["text"])) <= NODE_TEXT_BUDGET
        for node in contents
        for segment in node["data"]["content"]
        if segment["type"] == "text"
    )
    assert _flatten_text(contents) == body
    images = [
        segment["data"]["file"]
        for segment in _iter_segments(contents)
        if segment["type"] == "image"
    ]
    assert images == [
        f"https://i0.hdslb.com/bfs/new_dyn/{index}.png" for index in range(20)
    ]
    # 顶层预览只带元数据，不再随正文长度膨胀
    assert _preview_chars(nodes) < 300


@pytest.mark.asyncio
async def test_content_stays_inline_when_within_budget() -> None:
    body = "D" * NODE_TEXT_BUDGET
    nodes = await _build(_info(TextBlock(body)))

    assert [node["data"]["name"] for node in nodes] == ["图文信息", "正文"]
    assert _segment_types(nodes[1]) == ["text"]
    assert nodes[1]["data"]["content"][0]["data"]["text"] == body


@pytest.mark.asyncio
async def test_budget_overflow_nests_content() -> None:
    nodes = await _build(_info(TextBlock("E" * (NODE_TEXT_BUDGET + 1))))

    assert [node["data"]["name"] for node in nodes] == ["图文信息", "正文"]
    assert set(_segment_types(nodes[1])) == {"node"}
    assert [node["data"]["name"] for node in _content_nodes(nodes)] == [
        "正文 1/2",
        "正文 2/2",
    ]


@pytest.mark.asyncio
async def test_many_images_are_chunked_by_image_limit() -> None:
    nodes = await _build(
        _info(
            *(ImageBlock((f"https://i0.hdslb.com/{index}.jpg",)) for index in range(20))
        )
    )

    contents = _content_nodes(nodes)
    assert [len(node["data"]["content"]) for node in contents] == [9, 9, 2]
    assert _preview_chars(nodes) < 300


# ---------- 嵌套边界 ----------


@pytest.mark.asyncio
async def test_nested_cards_degrade_when_depth_is_zero() -> None:
    info = _info(
        TextBlock("正文"),
        OpusCardBlock(
            opus_id="1056353752004427792",
            title="另一篇图文",
            jump_url="https://www.bilibili.com/opus/1056353752004427792",
        ),
        VideoCardBlock(bvid="BV1xx411c7mD", title="视频卡片"),
    )
    config = _config(bilibili_opus_nested_depth=0)
    nodes = await _build(info, config=config)

    assert len(nodes) == 4
    assert nodes[2]["data"]["name"] == "链接卡片"
    assert "[图文] 另一篇图文" in nodes[2]["data"]["content"][0]["data"]["text"]
    assert "[视频] 视频卡片" in nodes[3]["data"]["content"][0]["data"]["text"]


@pytest.mark.asyncio
async def test_nested_cards_degrade_when_budget_is_exhausted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fetch = AsyncMock(return_value=_info(TextBlock("嵌套正文")))
    monkeypatch.setattr(opus_sender, "_fetch_opus_info", fetch)

    info = _info(
        TextBlock("正文"),
        *(
            OpusCardBlock(opus_id=str(index), title=f"卡片{index}")
            for index in range(1, 4)
        ),
    )
    config = _config(bilibili_opus_nested_max_cards=2)
    nodes = await _build(info, config=config)

    names = [node["data"]["name"] for node in nodes]
    assert names[0] == "图文信息"
    assert names[1] == "正文"
    assert names[2].startswith("嵌套图文")
    assert names[3].startswith("嵌套图文")
    assert names[4] == "链接卡片"
    assert fetch.await_count == 2


@pytest.mark.asyncio
async def test_nested_opus_nodes_are_recursive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    nested = _info(
        TextBlock("嵌套正文"),
        OpusCardBlock(opus_id="222", title="更深一层"),
        title="嵌套图文",
    )
    monkeypatch.setattr(opus_sender, "_fetch_opus_info", AsyncMock(return_value=nested))

    info = _info(TextBlock("正文"), OpusCardBlock(opus_id="111", title="一层"))
    nodes = await _build(info, config=_config())

    outer_nested = nodes[2]
    assert outer_nested["data"]["name"] == "嵌套图文: 一层"
    inner_forward = outer_nested["data"]["content"]
    assert isinstance(inner_forward, list)
    assert inner_forward[0]["data"]["name"] == "图文信息"
    assert inner_forward[1]["data"]["name"] == "正文"
    deeper = inner_forward[2]
    assert deeper["data"]["name"] == "嵌套图文: 更深一层"


@pytest.mark.asyncio
async def test_nested_opus_failure_renders_error_node(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        opus_sender,
        "_fetch_opus_info",
        AsyncMock(side_effect=OpusUnavailableError("gone")),
    )
    info = _info(TextBlock("正文"), OpusCardBlock(opus_id="111", title="一层"))

    nodes = await _build(info, config=_config())

    assert nodes[2]["data"]["name"] == "嵌套图文: 一层"
    assert "嵌套图文获取失败" in nodes[2]["data"]["content"]


@pytest.mark.asyncio
async def test_link_cards_become_their_own_nodes() -> None:
    info = _info(
        TextBlock("正文"),
        LinkCardBlock(title="活动", jump_url="https://www.bilibili.com/x"),
        LinkCardBlock(title="商品", cover_url="https://i0.hdslb.com/g.jpg"),
    )

    nodes = await _build(info, config=_config())

    assert [node["data"]["name"] for node in nodes] == [
        "图文信息",
        "正文",
        "链接卡片",
        "链接卡片",
    ]
    assert _segment_types(nodes[2]) == ["text"]
    assert (
        nodes[2]["data"]["content"][0]["data"]["text"]
        == "活动 — https://www.bilibili.com/x"
    )
    assert _segment_types(nodes[3]) == ["image", "text"]


# ---------- 嵌套视频 ----------


def _video_info() -> VideoInfo:
    return VideoInfo(
        bvid="BV1xx411c7mD",
        aid=123,
        title="投稿视频",
        duration=120,
        cover_url="https://i0.hdslb.com/v.jpg",
        up_name="UP",
        desc="简介",
        cid=456,
        page_duration=120,
        stats=VideoStats(view=100, like=1),
    )


@pytest.mark.asyncio
async def test_nested_video_downloads_file_and_attaches(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    video_path = tmp_path / "v.mp4"
    video_path.write_bytes(b"video")
    monkeypatch.setattr(
        opus_sender,
        "download_video",
        AsyncMock(return_value=(video_path, _video_info(), 80)),
    )
    monkeypatch.setattr(
        opus_sender,
        "build_bilibili_video_nodes",
        AsyncMock(return_value=(["nested"], [], None)),
    )
    monkeypatch.setattr(opus_sender, "cleanup_file", MagicMock())

    info = _info(
        TextBlock("正文"), VideoCardBlock(bvid="BV1xx411c7mD", title="投稿视频")
    )
    nodes = await _build(info, config=_config())

    assert nodes[2]["data"]["name"] == "嵌套视频: 投稿视频"
    assert nodes[2]["data"]["content"] == ["nested"]


@pytest.mark.asyncio
async def test_nested_video_falls_back_to_card_when_download_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        opus_sender, "download_video", AsyncMock(side_effect=RuntimeError("超时"))
    )
    monkeypatch.setattr(
        opus_sender, "get_video_info", AsyncMock(side_effect=RuntimeError("超时"))
    )

    info = _info(
        TextBlock("正文"),
        VideoCardBlock(
            bvid="BV1xx411c7mD",
            title="投稿视频",
            cover_url="https://i0.hdslb.com/v.jpg",
            jump_url="https://www.bilibili.com/video/BV1xx411c7mD",
        ),
    )
    nodes = await _build(info, config=_config())

    assert nodes[2]["data"]["name"] == "嵌套视频: 投稿视频"
    assert _segment_types(nodes[2]) == ["image", "text"]
    assert "视频处理失败" in nodes[2]["data"]["content"][1]["data"]["text"]


# ---------- 发送与错误语义 ----------


@pytest.mark.asyncio
async def test_send_opus_sends_forward_with_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        opus_sender,
        "_fetch_opus_info",
        AsyncMock(return_value=_info(TextBlock("正文"))),
    )
    sender = _sender()

    result = await opus_sender.send_opus(
        "933099353259638816",
        sender=sender,
        target_type="private",
        target_id=20001,
        config=_config(),
    )

    assert result.startswith("已发送 Bilibili 图文合并转发")
    sender.send_private_forward_message.assert_awaited_once()
    call = sender.send_private_forward_message.await_args
    assert call.args[0] == 20001
    assert len(call.args[1]) == 2
    assert call.kwargs["history_message"].startswith("[Bilibili 图文] 「测试图文」")


@pytest.mark.asyncio
async def test_send_opus_propagates_delivery_uncertain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        opus_sender,
        "_fetch_opus_info",
        AsyncMock(return_value=_info(TextBlock("正文"))),
    )
    sender = _sender()
    sender.send_group_forward_message.side_effect = OneBotDeliveryUncertainError(
        "send_forward_msg", "timeout"
    )

    with pytest.raises(OneBotDeliveryUncertainError):
        await opus_sender.send_opus(
            "933099353259638816",
            sender=sender,
            target_type="group",
            target_id=10001,
            config=_config(),
        )

    sender.send_group_forward_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_send_opus_raises_when_fetch_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        opus_sender,
        "_fetch_opus_info",
        AsyncMock(side_effect=OpusUnavailableError("图文不存在")),
    )
    sender = _sender()

    with pytest.raises(OpusUnavailableError):
        await opus_sender.send_opus(
            "1",
            sender=sender,
            target_type="group",
            target_id=10001,
            config=_config(),
        )

    sender.send_group_forward_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_opus_degrades_when_build_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        opus_sender,
        "_fetch_opus_info",
        AsyncMock(return_value=_info(TextBlock("正文"))),
    )
    monkeypatch.setattr(
        opus_sender, "build_opus_nodes", AsyncMock(side_effect=RuntimeError("构建失败"))
    )
    sender = _sender()

    result = await opus_sender.send_opus(
        "933099353259638816",
        sender=sender,
        target_type="group",
        target_id=10001,
        config=_config(),
    )

    assert result.startswith("处理失败，已发送 Bilibili 图文信息合并转发")
    sender.send_group_forward_message.assert_awaited_once()
    nodes = sender.send_group_forward_message.await_args.args[1]
    assert nodes[0]["data"]["name"] == "图文信息"
    assert nodes[1]["data"]["name"] == "正文"
    assert "构建失败" in nodes[1]["data"]["content"]


# ---------- 嵌套视频文件生命周期（回归：不能提前删除） ----------


@pytest.mark.asyncio
async def test_nested_video_file_survives_until_forward_is_sent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """嵌套视频的临时文件必须活到转发真正发出去之后。

    回归：此前 _nested_video_node 在 finally 里立刻 cleanup，而节点里只有
    file:// 路径，发送方会拿到已被删除的文件。
    """
    video_path = tmp_path / "v.mp4"
    video_path.write_bytes(b"video")
    seen: list[bool] = []

    async def _fake_build(info: Any, **kwargs: Any) -> tuple[Any, Any, Any]:
        # 节点构建时文件必须还在
        seen.append(video_path.exists())
        return [{"type": "video", "data": {"file": f"file://{video_path}"}}], [], None

    monkeypatch.setattr(opus_sender, "download_video", _download_video_stub(video_path))
    monkeypatch.setattr(
        opus_sender,
        "_fetch_opus_info",
        AsyncMock(
            return_value=_info(
                TextBlock("正文"), VideoCardBlock(bvid="BV1xx411c7mD", title="投稿视频")
            )
        ),
    )
    monkeypatch.setattr(opus_sender, "build_bilibili_video_nodes", _fake_build)
    removed: list[Path] = []
    monkeypatch.setattr(opus_sender, "cleanup_file", lambda p: removed.append(Path(p)))

    sender = _sender()

    async def _send(*args: Any, **kwargs: Any) -> None:
        # 发送时文件同样必须还在
        seen.append(video_path.exists())

    sender.send_group_forward_message = AsyncMock(side_effect=_send)

    await opus_sender.send_opus(
        "933099353259638816",
        sender=sender,
        target_type="group",
        target_id=10001,
        config=_config(),
    )

    assert seen == [True, True], "嵌套视频文件在构建或发送时已被删除"
    assert removed == [video_path], "发送结束后应清理一次临时文件"


@pytest.mark.asyncio
async def test_nested_video_file_is_cleaned_when_build_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    video_path = tmp_path / "v.mp4"
    video_path.write_bytes(b"video")
    monkeypatch.setattr(opus_sender, "download_video", _download_video_stub(video_path))
    monkeypatch.setattr(
        opus_sender,
        "_fetch_opus_info",
        AsyncMock(
            return_value=_info(
                TextBlock("正文"), VideoCardBlock(bvid="BV1xx411c7mD", title="视频")
            )
        ),
    )
    monkeypatch.setattr(
        opus_sender,
        "build_bilibili_video_nodes",
        AsyncMock(side_effect=RuntimeError("构建失败")),
    )
    pending_cleanup: list[Path] = []

    with pytest.raises(RuntimeError):
        await opus_sender.build_opus_nodes(
            _info(TextBlock("正文"), VideoCardBlock(bvid="BV1xx411c7mD", title="视频")),
            sender=_sender(),
            target_type="group",
            target_id=1,
            config=_config(),
            pending_cleanup=pending_cleanup,
        )

    # 构建失败时路径仍留在待清理列表里，交给调用方收尾，不会泄漏临时文件
    assert pending_cleanup == [video_path]


def _download_video_stub(video_path: Path) -> Any:
    return AsyncMock(return_value=(video_path, _video_info(), 80))
