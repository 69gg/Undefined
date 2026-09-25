"""B 站图文（opus）合并转发发送。

节点结构固定为：

1. 第一条节点：图文元数据（标题 / UP主 / 时间 / 数据 / 链接，含封面图）
2. 之后为内容节点：正文文本 + 图片，按单节点字数上限切分，顺序不变
3. 内容之后再追加嵌套节点：图文卡片 / 视频卡片各自成为独立转发节点，
   其它卡片渲染为单独一行节点

嵌套展开受 ``depth``（层数）与 ``budget``（单条图文最多展开多少张卡片）
约束，超出边界的卡片降级为纯文本节点，不再发请求。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from Undefined.bilibili.downloader import (
    QUALITY_MAP,
    cleanup_file,
    download_video,
    get_opus_item,
    get_video_info,
)
from Undefined.bilibili.errors import OpusUnavailableError
from Undefined.bilibili.format import (
    MAX_TEXT_LENGTH,
    format_timestamp,
    split_text_chunks,
)
from Undefined.bilibili.models import (
    ImageBlock,
    LinkCardBlock,
    OpusBlock,
    OpusCardBlock,
    OpusInfo,
    TextBlock,
    VideoCardBlock,
    VideoInfo,
)
from Undefined.bilibili.opus_render import (
    format_opus_history_message,
    format_opus_info,
    format_opus_stats,
    parse_opus_item,
)
from Undefined.bilibili.sender import build_bilibili_video_nodes
from Undefined.utils.io import get_file_size

if TYPE_CHECKING:
    from Undefined.utils.sender import MessageSender

logger = logging.getLogger(__name__)

_BOT_NAME = "Undefined"
_DEFAULT_BOT_UIN = "10000"

# ``output_mode=uid`` 默认最多登记多少张图片，避免超大图文刷满附件表
_UID_IMAGE_LIMIT = 9

# 获取失败时可降级的语义（投递不确定 / 文件传输错误必须上抛）
_FATAL_ERROR_FLAGS = ("delivery_uncertain", "file_transfer_error")


class _ExpansionBudget:
    """单条图文的嵌套卡片展开预算。"""

    def __init__(self, limit: int) -> None:
        self.remaining = max(0, int(limit))

    def claim(self) -> bool:
        if self.remaining <= 0:
            return False
        self.remaining -= 1
        return True


def _node(
    content: str | list[dict[str, Any]], *, name: str = _BOT_NAME
) -> dict[str, Any]:
    return {
        "type": "node",
        "data": {
            "name": name,
            "uin": _DEFAULT_BOT_UIN,
            "content": content,
        },
    }


# ---------- 节点内容构建 ----------


def _meta_lines(info: OpusInfo) -> list[str]:
    lines = [
        f"「{info.title or '无标题'}」",
        f"UP主: {info.author.name or '未知'}",
    ]
    published = format_timestamp(info.pub_ts)
    if published:
        lines.append(f"时间: {published}")
    lines.append(format_opus_stats(info.stats, view_label="阅读"))
    if info.is_forward and info.forward_origin is not None:
        origin = info.forward_origin.name or "未知"
        lines.append(f"转发自: {origin}")
    lines.extend(["---", info.url])
    return lines


def _build_meta_node(info: OpusInfo) -> dict[str, Any]:
    segments: list[dict[str, Any]] = []
    if info.cover_url:
        segments.append({"type": "image", "data": {"file": info.cover_url}})
    segments.append({"type": "text", "data": {"text": "\n".join(_meta_lines(info))}})
    return _node(segments, name="图文信息")


def render_blocks_to_nodes(
    blocks: tuple[OpusBlock, ...],
    *,
    limit: int = MAX_TEXT_LENGTH,
    node_name: str = "正文",
) -> list[dict[str, Any]]:
    """把块序列渲染成内容节点列表。

    - 文本块按 ``limit`` 切分，切分点之后的内容落在新节点；
    - 图片块作为消息段插入当前位置，可与文本共处同一节点；
    - 节点只有在非空时才会产生。
    """
    node_segments_list: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []

    def flush() -> None:
        nonlocal current
        if current:
            node_segments_list.append(current)
            current = []

    def append_text(text: str) -> None:
        nonlocal current
        chunks = split_text_chunks(text, limit)
        for index, chunk in enumerate(chunks):
            if index > 0:
                flush()
            if chunk:
                current.append({"type": "text", "data": {"text": chunk}})

    for block in blocks:
        if isinstance(block, TextBlock):
            append_text(block.text)
        elif isinstance(block, ImageBlock):
            for url in block.urls:
                if url:
                    current.append({"type": "image", "data": {"file": url}})
        else:
            append_text(_card_block_text(block))
    flush()

    if not node_segments_list:
        node_segments_list = [[{"type": "text", "data": {"text": "（无内容）"}}]]

    total = len(node_segments_list)
    return [
        _node(
            segments,
            name=f"{node_name} {index}/{total}" if total > 1 else node_name,
        )
        for index, segments in enumerate(node_segments_list, start=1)
    ]


def _card_block_text(block: OpusBlock) -> str:
    if isinstance(block, VideoCardBlock):
        label = "视频"
    elif isinstance(block, OpusCardBlock):
        label = "图文"
    else:
        label = "卡片"

    parts = [f"[{label}]"]
    if isinstance(block, (VideoCardBlock, OpusCardBlock, LinkCardBlock)):
        if block.title:
            parts.append(block.title)
        if block.jump_url:
            parts.append(block.jump_url)
    return " ".join(parts)


def _link_card_node(block: LinkCardBlock) -> dict[str, Any]:
    segments: list[dict[str, Any]] = []
    if block.cover_url:
        segments.append({"type": "image", "data": {"file": block.cover_url}})
    parts = [part for part in (block.title, block.jump_url) if part]
    segments.append({"type": "text", "data": {"text": " — ".join(parts) or "链接卡片"}})
    return _node(segments, name="链接卡片")


# ---------- 嵌套卡片 ----------


async def _nested_opus_node(
    block: OpusCardBlock,
    *,
    sender: "MessageSender",
    target_type: Literal["group", "private"],
    target_id: int,
    cookie: str,
    config: Any,
    budget: _ExpansionBudget,
    depth: int,
    pending_cleanup: list[Path],
) -> dict[str, Any]:
    label = f"嵌套图文: {block.title}" if block.title else "嵌套图文"
    try:
        info = await _fetch_opus_info(block.opus_id, cookie=cookie, config=config)
        nested_nodes = await build_opus_nodes(
            info,
            sender=sender,
            target_type=target_type,
            target_id=target_id,
            cookie=cookie,
            config=config,
            budget=budget,
            depth=depth,
            pending_cleanup=pending_cleanup,
        )
        return _node(nested_nodes, name=label)
    except Exception as exc:
        logger.warning(
            "[Bilibili] 嵌套图文获取失败: opus=%s err=%s", block.opus_id, exc
        )
        return _node(f"嵌套图文获取失败: {exc}", name=label)


async def _resolve_nested_video(
    block: VideoCardBlock,
    *,
    cookie: str,
    config: Any,
) -> tuple[Path | None, VideoInfo | None, str, str]:
    """下载嵌套视频卡片对应的视频文件。

    Returns:
        (视频文件路径 | None, 视频信息 | None, 视频状态文案, 信息节点前缀)
    """
    if not block.bvid:
        return None, None, "未下载视频（卡片缺少 BV 号）", ""

    prefer_quality = int(_config_value(config, "bilibili_prefer_quality", 80))
    max_duration = int(_config_value(config, "bilibili_max_duration", 600))
    max_file_size = int(_config_value(config, "bilibili_max_file_size", 100))
    oversize_strategy = str(
        _config_value(config, "bilibili_oversize_strategy", "downgrade")
    )

    video_path: Path | None = None
    video_info: VideoInfo | None = None
    video_status = "未发送视频"
    info_prefix = ""
    try:
        video_path, video_info, actual_qn = await download_video(
            bvid=block.bvid,
            cookie=cookie,
            prefer_quality=prefer_quality,
            max_duration=max_duration,
        )
        if video_path is None:
            video_status = f"视频时长 {video_info.duration}s 超过限制，仅发送信息"
            info_prefix = f"({video_status})"
        else:
            file_size_mb = await get_file_size(video_path) / 1024 / 1024
            max_size = max_file_size if max_file_size > 0 else float("inf")
            if file_size_mb > max_size:
                if oversize_strategy == "downgrade" and actual_qn > 32:
                    cleanup_file(video_path)
                    video_path = None
                    video_path, video_info, actual_qn = await download_video(
                        bvid=block.bvid,
                        cookie=cookie,
                        prefer_quality=_lower_quality(actual_qn),
                        max_duration=max_duration,
                    )
                    if video_path is not None:
                        file_size_mb = await get_file_size(video_path) / 1024 / 1024
                if video_path is not None and file_size_mb > max_size:
                    cleanup_file(video_path)
                    video_path = None
                    video_status = f"视频文件 {file_size_mb:.1f}MB 超过限制，仅发送信息"
                    info_prefix = f"({video_status})"
            if video_path is not None:
                quality_name = QUALITY_MAP.get(actual_qn, str(actual_qn))
                video_status = f"已附加视频 ({quality_name}, {file_size_mb:.1f}MB)"
    except Exception as exc:
        logger.warning("[Bilibili] 嵌套视频下载失败: bvid=%s err=%s", block.bvid, exc)
        if video_path is not None:
            cleanup_file(video_path)
            video_path = None
        video_status = f"视频处理失败: {exc}"
        info_prefix = f"({video_status})"
        try:
            video_info = await get_video_info(block.bvid, cookie=cookie)
        except Exception:
            video_info = None

    return video_path, video_info, video_status, info_prefix


def _lower_quality(current_qn: int) -> int:
    for qn in sorted(QUALITY_MAP.keys(), reverse=True):
        if qn < current_qn:
            return qn
    return 32


async def _nested_video_node(
    block: VideoCardBlock,
    *,
    cookie: str,
    config: Any,
    pending_cleanup: list[Path],
) -> dict[str, Any]:
    label = f"嵌套视频: {block.title}" if block.title else "嵌套视频"

    video_path, video_info, video_status, info_prefix = await _resolve_nested_video(
        block, cookie=cookie, config=config
    )
    # 视频文件要等到外层转发真正发出去之后才能删：节点里只留 file:// 路径，
    # 提前清理会让发送方拿到已经不存在的文件。路径交给调用方统一收尾。
    if video_path is not None:
        pending_cleanup.append(video_path)

    if video_info is None:
        # 拿不到视频信息时退化为卡片信息节点
        lines = [f"「{block.title or '视频'}」", f"BV: {block.bvid or '未知'}"]
        if block.jump_url:
            lines.extend(["---", block.jump_url])
        segments: list[dict[str, Any]] = []
        if block.cover_url:
            segments.append({"type": "image", "data": {"file": block.cover_url}})
        segments.append(
            {
                "type": "text",
                "data": {"text": f"{video_status}\n" + "\n".join(lines)},
            }
        )
        return _node(segments, name=label)

    danmaku_enabled = bool(_config_value(config, "bilibili_danmaku_enabled", True))
    nodes, _danmaku, _error = await build_bilibili_video_nodes(
        video_info,
        video_path=video_path,
        video_status=video_status,
        info_prefix=info_prefix,
        cookie=cookie,
        danmaku_enabled=danmaku_enabled,
        danmaku_batch_size=int(
            _config_value(config, "bilibili_danmaku_batch_size", 100)
        ),
        danmaku_max_count=int(_config_value(config, "bilibili_danmaku_max_count", 0)),
        info_node_name=label,
    )
    return _node(nodes, name=label)


def _config_value(config: Any, name: str, default: Any) -> Any:
    value = getattr(config, name, None)
    return default if value is None else value


# ---------- 顶层构建 ----------


async def build_opus_nodes(
    info: OpusInfo,
    *,
    sender: "MessageSender",
    target_type: Literal["group", "private"],
    target_id: int,
    cookie: str = "",
    config: Any = None,
    budget: _ExpansionBudget | None = None,
    depth: int = 0,
    pending_cleanup: list[Path] | None = None,
) -> list[dict[str, Any]]:
    """按「元数据 → 内容 → 嵌套」顺序构建合并转发节点。

    ``pending_cleanup`` 收集嵌套视频下载产生的临时文件，由调用方在转发
    真正发出之后统一清理（节点里只有 ``file://`` 路径，提前删会发不出去）。
    """
    max_depth = int(_config_value(config, "bilibili_opus_nested_depth", 5))
    max_cards = int(_config_value(config, "bilibili_opus_nested_max_cards", 8))
    if budget is None:
        budget = _ExpansionBudget(max_cards)
    if pending_cleanup is None:
        pending_cleanup = []

    nodes: list[dict[str, Any]] = [_build_meta_node(info)]
    nodes.extend(render_blocks_to_nodes(info.blocks))

    for block in info.blocks:
        if isinstance(block, LinkCardBlock):
            nodes.append(_link_card_node(block))
            continue
        if not isinstance(block, (OpusCardBlock, VideoCardBlock)):
            continue
        if depth >= max_depth or not budget.claim():
            logger.info(
                "[Bilibili] 嵌套展开达到边界，降级为文本节点: depth=%s/%s remaining=%s",
                depth,
                max_depth,
                budget.remaining,
            )
            nodes.append(_link_card_node(_block_to_link_card(block)))
            continue
        if isinstance(block, OpusCardBlock):
            nodes.append(
                await _nested_opus_node(
                    block,
                    sender=sender,
                    target_type=target_type,
                    target_id=target_id,
                    cookie=cookie,
                    config=config,
                    budget=budget,
                    depth=depth + 1,
                    pending_cleanup=pending_cleanup,
                )
            )
        else:
            nodes.append(
                await _nested_video_node(
                    block,
                    cookie=cookie,
                    config=config,
                    pending_cleanup=pending_cleanup,
                )
            )
    return nodes


def _block_to_link_card(block: OpusBlock) -> LinkCardBlock:
    if isinstance(block, VideoCardBlock):
        return LinkCardBlock(
            title=f"[视频] {block.title}".strip() or "视频卡片",
            jump_url=block.jump_url,
            cover_url=block.cover_url,
        )
    if isinstance(block, OpusCardBlock):
        return LinkCardBlock(
            title=f"[图文] {block.title}".strip() or "图文卡片",
            jump_url=block.jump_url,
            cover_url=block.cover_url,
        )
    if isinstance(block, LinkCardBlock):
        return block
    return LinkCardBlock(title="链接卡片")


async def _fetch_opus_info(opus_id: str, *, cookie: str, config: Any) -> OpusInfo:
    item = await get_opus_item(opus_id, cookie=cookie)
    return parse_opus_item(item).info


async def fetch_opus_info(opus_id: str, *, cookie: str = "") -> OpusInfo:
    """只获取图文信息（``output_mode=info`` 使用，不发送、不注册附件）。"""
    return await _fetch_opus_info(opus_id, cookie=cookie, config=None)


# ---------- 附件 UID / 纯信息模式 ----------


def format_opus_uid_message(
    info: OpusInfo,
    *,
    uids: list[str],
    image_total: int,
    failures: list[str] | None = None,
) -> str:
    """生成 ``output_mode=uid`` 的返回文案（含 ``<attachment uid=.../>``）。"""
    lines = [
        f"已获取 Bilibili 图文：{info.title or '无标题'}",
        f"图文 ID: {info.opus_id}",
        f"UP主: {info.author.name or '未知'}",
        format_opus_stats(info.stats),
    ]
    published = format_timestamp(info.pub_ts)
    if published:
        lines.append(f"发布时间: {published}")
    lines.append(f"图片: 已登记 {len(uids)}/{image_total} 张")
    lines.extend(
        f'图片 {index}: <attachment uid="{uid}"/>'
        for index, uid in enumerate(uids, start=1)
    )
    for failure in failures or []:
        lines.append(f"图片登记失败: {failure}")
    lines.append(info.url)
    return "\n".join(lines)


async def fetch_bilibili_opus_attachment(
    opus_id: str,
    *,
    attachment_registry: Any,
    scope_key: str,
    cookie: str = "",
    config: Any = None,
    max_images: int = _UID_IMAGE_LIMIT,
) -> str:
    """获取图文并把图片注册为当前会话附件 UID（不发送消息）。"""
    if not str(opus_id or "").strip():
        return "图文 ID 不能为空"
    if attachment_registry is None:
        return "缺少必要的运行时组件（attachment_registry）"
    if not str(scope_key or "").strip():
        return "无法确定附件作用域，不能注册图文图片"

    info = await _fetch_opus_info(str(opus_id), cookie=cookie, config=config)
    images = info.images
    if not images:
        return f"{format_opus_info(info)}\n\n（该图文没有可登记的图片）"

    limit = max(1, int(max_images))
    uids: list[str] = []
    failures: list[str] = []
    for index, url in enumerate(images[:limit], start=1):
        try:
            record = await attachment_registry.register_remote_url(
                scope_key,
                url,
                kind="image",
                source_kind="bilibili_opus",
                source_ref=info.url,
                segment_data={"opus_id": info.opus_id, "title": info.title},
            )
        except Exception as exc:
            logger.warning(
                "[Bilibili] 图文图片登记失败: opus=%s #%s err=%s", opus_id, index, exc
            )
            failures.append(f"#{index} {exc}")
            continue
        uids.append(str(record.uid))

    message = format_opus_uid_message(
        info,
        uids=uids,
        image_total=len(images),
        failures=failures,
    )
    if len(images) > limit:
        message = f"{message}\n（仅登记前 {limit} 张图片，其余请见原文链接）"
    return message


# ---------- 发送 ----------


async def _send_forward(
    sender: "MessageSender",
    target_type: Literal["group", "private"],
    target_id: int,
    nodes: list[dict[str, Any]],
    *,
    history_message: str,
) -> None:
    if target_type == "group":
        await sender.send_group_forward_message(
            target_id, nodes, history_message=history_message
        )
    else:
        await sender.send_private_forward_message(
            target_id, nodes, history_message=history_message
        )


def _is_fatal_error(exc: BaseException) -> bool:
    return any(bool(getattr(exc, flag, False)) for flag in _FATAL_ERROR_FLAGS)


async def send_opus(
    opus_id: str,
    *,
    sender: "MessageSender",
    target_type: Literal["group", "private"],
    target_id: int,
    cookie: str = "",
    config: Any = None,
    budget: _ExpansionBudget | None = None,
    depth: int = 0,
) -> str:
    """获取图文并发送合并转发，返回可读结果文案。"""
    info: OpusInfo | None = None
    # 嵌套视频下载的临时文件：转发真正发出（或彻底失败）之后才清理
    pending_cleanup: list[Path] = []
    try:
        info = await _fetch_opus_info(opus_id, cookie=cookie, config=config)
        nodes = await build_opus_nodes(
            info,
            sender=sender,
            target_type=target_type,
            target_id=target_id,
            cookie=cookie,
            config=config,
            budget=budget,
            depth=depth,
            pending_cleanup=pending_cleanup,
        )
        await _send_forward(
            sender,
            target_type,
            target_id,
            nodes,
            history_message=format_opus_history_message(info),
        )
        return f"已发送 Bilibili 图文合并转发「{info.title or info.opus_id}」"
    except Exception as exc:
        if _is_fatal_error(exc):
            raise
        logger.exception("[Bilibili] 图文处理失败: %s", opus_id)
        if info is None:
            raise OpusUnavailableError(f"图文处理失败: {exc}") from exc
        failure_status = f"图文处理失败: {exc}"
        try:
            nodes = [
                _build_meta_node(info),
                _node(failure_status, name="正文"),
            ]
            await _send_forward(
                sender,
                target_type,
                target_id,
                nodes,
                history_message=format_opus_history_message(info),
            )
        except Exception as fallback_exc:
            if _is_fatal_error(fallback_exc):
                raise
            raise OpusUnavailableError(f"图文处理失败: {exc}") from fallback_exc
        return f"处理失败，已发送 Bilibili 图文信息合并转发: {exc}"
    finally:
        for path in pending_cleanup:
            cleanup_file(path)


__all__ = [
    "build_opus_nodes",
    "fetch_bilibili_opus_attachment",
    "fetch_opus_info",
    "format_opus_uid_message",
    "render_blocks_to_nodes",
    "send_opus",
]
