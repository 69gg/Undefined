"""图文响应解析与消息段渲染（纯函数，无 IO）。

同一个 ``data.item`` 可能来自两个接口，结构不同：

- ``x/polymer/web-dynamic/v1/opus/detail``：``modules`` 是 **列表**，按
  ``module_type`` 区分标题 / 作者 / 内容 / 统计等模块。
- ``x/polymer/web-dynamic/v1/detail``：``modules`` 是 **字典**，正文在
  ``module_dynamic.desc.text``，图片 / 卡片在 ``module_dynamic.major``。

本模块同时兼容两种形态，并把段落转换为 :mod:`Undefined.bilibili.models`
里的 ``OpusBlock`` 序列，供发送层拼装合并转发节点。
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
import re
from typing import Any

from Undefined.bilibili.format import format_count, format_timestamp
from Undefined.bilibili.models import (
    ImageBlock,
    LinkCardBlock,
    OpusAuthor,
    OpusBlock,
    OpusCardBlock,
    OpusInfo,
    OpusStats,
    TextBlock,
    VideoCardBlock,
)

logger = logging.getLogger(__name__)

OPUS_URL_TEMPLATE = "https://www.bilibili.com/opus/{opus_id}"
_BV_PATTERN = re.compile(r"BV1[1-9A-HJ-NP-Za-km-z]{9}")
_OPUS_ID_PATTERN = re.compile(r"/opus/(\d+)")
_EMOJI_PLACEHOLDER = "[表情]"
_EMPTY_BODY_PLACEHOLDER = "（该图文没有正文内容）"

# para_type 常量
_PARA_TEXT = 1
_PARA_IMAGE = 2
_PARA_LINE = 3
_PARA_QUOTE = 4
_PARA_LIST = 5
_PARA_LINK_CARD = 6
_PARA_CODE = 7

# 未知卡片类型的兜底文案
_CARD_TITLE_FALLBACK = "链接卡片"


@dataclass(slots=True, frozen=True)
class ParsedOpus:
    """图文解析结果。"""

    info: OpusInfo
    stats: OpusStats
    author: OpusAuthor


# ---------- 通用取值助手 ----------


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _as_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return ""
    if isinstance(value, (int, float)):
        return str(value)
    return ""


def _as_int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return 0
    return 0


def _first_nonempty(*values: Any) -> str:
    for value in values:
        text = _as_str(value).strip()
        if text:
            return text
    return ""


def _absolutize(url: str) -> str:
    """把 B 站返回的无协议 / 协议相对 URL 补齐为 https。"""
    text = url.strip()
    if not text:
        return ""
    if text.startswith("//"):
        return f"https:{text}"
    if text.startswith(("http://", "https://")):
        return text
    return f"https://{text.lstrip('/')}"


# ---------- 富文本节点 ----------


def _render_rich_node(rich: dict[str, Any]) -> str:
    """把 ``TEXT_NODE_TYPE_RICH`` 节点渲染成文本。"""
    node_type = _as_str(rich.get("type")).upper()
    text = _first_nonempty(rich.get("orig_text"), rich.get("text"))
    jump_url = _absolutize(_as_str(rich.get("jump_url")))

    if node_type.endswith("EMOJI"):
        return text or _EMOJI_PLACEHOLDER
    if node_type.endswith("VIEW_PICTURE"):
        return "[图片]"
    if node_type.endswith("FORMULA"):
        latex = _first_nonempty(_as_dict(rich.get("formula")).get("latex_content"))
        return f"${latex}$" if latex else text
    if jump_url and text and jump_url not in text:
        return f"{text} ({jump_url})"
    return text or jump_url


def _render_text_nodes(nodes: Any) -> str:
    """把段落里的文本节点数组渲染成一段文本。"""
    parts: list[str] = []
    for raw_node in _as_list(nodes):
        node = _as_dict(raw_node)
        node_type = _as_str(node.get("type")).upper()
        if node_type == "TEXT_NODE_TYPE_WORD":
            parts.append(_as_str(_as_dict(node.get("word")).get("words")))
        elif node_type == "TEXT_NODE_TYPE_RICH":
            parts.append(_render_rich_node(_as_dict(node.get("rich"))))
        elif node_type == "TEXT_NODE_TYPE_FORMULA":
            latex = _first_nonempty(_as_dict(node.get("formula")).get("latex_content"))
            parts.append(f"${latex}$" if latex else "")
    return "".join(parts)


# ---------- 卡片 ----------


def _card_title_and_url(card: dict[str, Any]) -> tuple[str, str, str]:
    """从任意卡片结构中尽力取出「标题 / 跳转链接 / 封面」。"""
    title = ""
    jump_url = ""
    cover = ""

    for key in ("opus", "common", "ugc", "goods", "live", "music", "vote"):
        candidate = _as_dict(card.get(key))
        if not candidate:
            continue
        title = title or _first_nonempty(candidate.get("title"), candidate.get("name"))
        jump_url = jump_url or _as_str(candidate.get("jump_url"))
        cover = cover or _as_str(candidate.get("cover"))
    item_null = _as_dict(card.get("item_null"))
    if not title and item_null:
        title = _first_nonempty(item_null.get("text"))

    return (
        title or _CARD_TITLE_FALLBACK,
        _absolutize(jump_url),
        _absolutize(cover),
    )


def _opus_card_ref(card: dict[str, Any], opus: dict[str, Any]) -> OpusCardBlock:
    """把 ``LINK_CARD_TYPE_OPUS`` 卡片转成图文引用。"""
    title, jump_url, cover = _card_title_and_url(card)
    opus_id = ""
    oid = _as_str(card.get("oid")).strip()
    if oid.isdigit():
        opus_id = oid
    if not opus_id:
        match = _OPUS_ID_PATTERN.search(jump_url)
        if match:
            opus_id = match.group(1)
    author = _as_dict(opus.get("author"))
    if not title:
        title = _first_nonempty(opus.get("title"), author.get("name"))
    return OpusCardBlock(
        opus_id=opus_id,
        title=title or _CARD_TITLE_FALLBACK,
        cover_url=cover or _absolutize(_as_str(opus.get("cover"))),
        jump_url=jump_url
        or (OPUS_URL_TEMPLATE.format(opus_id=opus_id) if opus_id else ""),
    )


def _parse_link_card(paragraph: dict[str, Any]) -> OpusBlock | None:
    """解析 ``para_type=6`` 的链接卡片段落。"""
    card = _as_dict(_as_dict(paragraph.get("link_card")).get("card"))
    if not card:
        return None

    card_type = _as_str(card.get("type")).upper()
    if card_type == "LINK_CARD_TYPE_OPUS":
        return _opus_card_ref(card, _as_dict(card.get("opus")))

    if card_type == "LINK_CARD_TYPE_UGC":
        ugc = _as_dict(card.get("ugc"))
        title, jump_url, cover = _card_title_and_url(card)
        bvid = _first_nonempty(ugc.get("bvid"))
        if not bvid:
            match = _BV_PATTERN.search(jump_url)
            if match:
                bvid = match.group(0)
        return VideoCardBlock(
            bvid=bvid,
            title=title or _CARD_TITLE_FALLBACK,
            cover_url=cover or _absolutize(_as_str(ugc.get("cover"))),
            jump_url=jump_url,
        )

    title, jump_url, cover = _card_title_and_url(card)
    return LinkCardBlock(title=title, jump_url=jump_url, cover_url=cover)


# ---------- 段落 ----------


def _parse_list_paragraph(paragraph: dict[str, Any]) -> OpusBlock | None:
    list_data = _as_dict(paragraph.get("list"))
    items = _as_list(list_data.get("items"))
    if not items:
        return None

    ordered = _as_int(list_data.get("style")) == 1
    lines: list[str] = []
    for index, raw_item in enumerate(items, start=1):
        item = _as_dict(raw_item)
        text = _render_text_nodes(item.get("nodes"))
        if not text.strip():
            continue
        level = max(0, _as_int(item.get("level")))
        indent = "  " * level
        if ordered:
            order = _as_int(item.get("order")) or index
            lines.append(f"{indent}{order}. {text}")
        else:
            lines.append(f"{indent}- {text}")
    return TextBlock("\n".join(lines)) if lines else None


def _parse_paragraph(paragraph: dict[str, Any]) -> OpusBlock | None:
    para_type = _as_int(paragraph.get("para_type"))

    if para_type == _PARA_IMAGE:
        urls = tuple(
            url
            for url in (
                _absolutize(_as_str(_as_dict(pic).get("url")))
                for pic in _as_list(_as_dict(paragraph.get("pic")).get("pics"))
            )
            if url
        )
        return ImageBlock(urls) if urls else None

    if para_type == _PARA_LINE:
        line_pic = _as_dict(_as_dict(paragraph.get("line")).get("pic"))
        pic_url = _absolutize(_as_str(line_pic.get("url")))
        return ImageBlock((pic_url,)) if pic_url else TextBlock("———")

    if para_type == _PARA_QUOTE:
        blockquote = _as_dict(paragraph.get("blockquote"))
        source = blockquote or paragraph
        text = _render_text_nodes(_as_dict(source.get("text")).get("nodes"))
        if not text.strip():
            return None
        quoted = "\n".join(f"> {line}" if line else ">" for line in text.split("\n"))
        return TextBlock(quoted)

    if para_type == _PARA_LIST:
        return _parse_list_paragraph(paragraph)

    if para_type == _PARA_LINK_CARD:
        return _parse_link_card(paragraph)

    if para_type == _PARA_CODE:
        code = _as_dict(paragraph.get("code"))
        content = _as_str(code.get("content"))
        if not content:
            return None
        lang = _as_str(code.get("lang")).replace("language-", "").strip()
        return TextBlock(f"```{lang}\n{content}\n```")

    if para_type in (0, _PARA_TEXT):
        text = _render_text_nodes(_as_dict(paragraph.get("text")).get("nodes"))
        return TextBlock(text) if text.strip() else None

    # 未知段落类型：尽力按文本处理
    text = _render_text_nodes(_as_dict(paragraph.get("text")).get("nodes"))
    return TextBlock(text) if text.strip() else None


def _parse_blocks_from_paragraphs(paragraphs: Any) -> tuple[OpusBlock, ...]:
    blocks: list[OpusBlock] = []
    for raw_paragraph in _as_list(paragraphs):
        block = _parse_paragraph(_as_dict(raw_paragraph))
        if block is not None:
            blocks.append(block)
    return tuple(blocks)


# ---------- 模块 ----------


def _author_from_module(module_author: dict[str, Any]) -> OpusAuthor:
    return OpusAuthor(
        mid=_as_int(module_author.get("mid")),
        name=_as_str(module_author.get("name")).strip(),
        avatar_url=_absolutize(_as_str(module_author.get("face"))),
    )


def _stats_from_module(module_stat: dict[str, Any]) -> OpusStats:
    def count(key: str) -> int:
        return _as_int(_as_dict(module_stat.get(key)).get("count"))

    return OpusStats(
        view=count("view"),
        like=count("like"),
        comment=count("comment"),
        repost=count("forward"),
        coin=count("coin"),
        favorite=count("favorite"),
    )


def _first_cover(blocks: tuple[OpusBlock, ...]) -> str:
    for block in blocks:
        if isinstance(block, ImageBlock) and block.urls:
            return block.urls[0]
        if isinstance(block, (VideoCardBlock, OpusCardBlock, LinkCardBlock)):
            if block.cover_url:
                return block.cover_url
    return ""


def _self_opus_block(opus: dict[str, Any], opus_id: str) -> OpusBlock | None:
    """``MAJOR_TYPE_OPUS`` 的 major 块：指向自己时不是卡片，避免自引用递归。"""
    jump_url = _absolutize(_as_str(opus.get("jump_url")))
    match = _OPUS_ID_PATTERN.search(jump_url)
    ref_id = match.group(1) if match else ""
    if ref_id and ref_id == opus_id:
        return None
    return OpusCardBlock(
        opus_id=ref_id,
        title=_as_str(opus.get("title")),
        cover_url=_absolutize(_as_str(opus.get("cover"))),
        jump_url=jump_url,
    )


def _major_block(major: dict[str, Any], opus_id: str = "") -> OpusBlock | None:
    major_type = _as_str(major.get("type")).upper()
    if major_type == "MAJOR_TYPE_ARCHIVE":
        archive = _as_dict(major.get("archive"))
        return VideoCardBlock(
            bvid=_as_str(archive.get("bvid")),
            title=_as_str(archive.get("title")),
            cover_url=_absolutize(_as_str(archive.get("cover"))),
            jump_url=_absolutize(_as_str(archive.get("jump_url"))),
        )
    if major_type == "MAJOR_TYPE_OPUS":
        return _self_opus_block(_as_dict(major.get("opus")), opus_id)
    if major_type in ("MAJOR_TYPE_COMMON", "MAJOR_TYPE_LIVE_RCMD"):
        title, jump_url, cover = _card_title_and_url(major)
        return LinkCardBlock(title=title, jump_url=jump_url, cover_url=cover)
    if major_type in ("MAJOR_TYPE_DRAW", "MAJOR_TYPE_ARTICLE"):
        return None
    return None


def _major_opus_blocks(major: dict[str, Any], opus_id: str) -> tuple[OpusBlock, ...]:
    """通用动态接口下正文位于 ``major.opus.summary``，长文只给摘要。"""
    opus = _as_dict(major.get("opus"))
    if not opus:
        return ()
    summary = _as_dict(opus.get("summary"))

    blocks = _parse_blocks_from_paragraphs(summary.get("paragraphs"))
    if not blocks:
        text = (
            _as_str(summary.get("text")).strip()
            or _render_text_nodes(summary.get("rich_text_nodes")).strip()
        )
        if text:
            blocks = (TextBlock(text),)

    pic_urls = tuple(
        url
        for url in (
            _absolutize(_as_str(_as_dict(pic).get("url")))
            for pic in _as_list(opus.get("pics"))
        )
        if url
    )
    if pic_urls:
        blocks = (*blocks, ImageBlock(pic_urls))
    if summary.get("has_more"):
        blocks = (*blocks, TextBlock("（仅摘要，完整正文请见原文链接）"))
    return blocks


def _parse_dict_modules(modules: dict[str, Any], opus_id: str) -> ParsedOpus:
    """解析 ``web-dynamic/v1/detail`` 的字典形态 modules。"""
    module_author = _as_dict(modules.get("module_author"))
    author = _author_from_module(module_author)
    stats = _stats_from_module(_as_dict(modules.get("module_stat")))

    dynamic = _as_dict(modules.get("module_dynamic"))
    blocks = _parse_blocks_from_paragraphs(dynamic.get("paragraphs"))

    major = _as_dict(dynamic.get("major"))
    major_type = _as_str(major.get("type")).upper()
    if major_type == "MAJOR_TYPE_OPUS":
        # 通用动态接口把正文放在 major.opus.summary 里
        blocks = (*blocks, *_major_opus_blocks(major, opus_id))
    if not blocks:
        desc_text = _as_str(_as_dict(dynamic.get("desc")).get("text"))
        if desc_text.strip():
            blocks = (TextBlock(desc_text),)
    if not blocks:
        major_block = _major_block(major, opus_id)
        if major_block is not None:
            blocks = (major_block,)

    draw_items = _as_list(_as_dict(major.get("draw")).get("items"))
    if draw_items:
        urls = tuple(
            url
            for url in (
                _absolutize(_as_str(_as_dict(item).get("src"))) for item in draw_items
            )
            if url
        )
        if urls:
            blocks = (*blocks, ImageBlock(urls))

    info = OpusInfo(
        opus_id=opus_id,
        title="",
        blocks=blocks,
        author=author,
        stats=stats,
        pub_ts=_as_int(module_author.get("pub_ts")),
        cover_url=_first_cover(blocks),
        dynamic_type_id=_as_str(dynamic.get("type")),
    )
    return ParsedOpus(info=info, stats=stats, author=author)


def _parse_list_modules(modules: list[Any], opus_id: str) -> ParsedOpus:
    """解析 ``opus/detail`` 的列表形态 modules。"""
    by_type: dict[str, dict[str, Any]] = {}
    for raw_module in modules:
        module = _as_dict(raw_module)
        module_type = _as_str(module.get("module_type")).upper()
        if module_type:
            by_type[module_type] = module

    author_module = _as_dict(by_type.get("MODULE_TYPE_AUTHOR"))
    module_author = _as_dict(author_module.get("module_author"))
    author = _author_from_module(module_author)
    stats = _stats_from_module(
        _as_dict(_as_dict(by_type.get("MODULE_TYPE_STAT")).get("module_stat"))
    )
    title = _as_str(
        _as_dict(_as_dict(by_type.get("MODULE_TYPE_TITLE")).get("module_title")).get(
            "text"
        )
    ).strip()

    content_module = _as_dict(by_type.get("MODULE_TYPE_CONTENT"))
    module_content = _as_dict(content_module.get("module_content"))
    blocks = _parse_blocks_from_paragraphs(module_content.get("paragraphs"))
    if not blocks:
        blocks = (TextBlock(_EMPTY_BODY_PLACEHOLDER),)

    info = OpusInfo(
        opus_id=opus_id,
        title=title,
        blocks=blocks,
        author=author,
        stats=stats,
        pub_ts=_as_int(module_author.get("pub_ts")),
        cover_url=_first_cover(blocks),
    )
    return ParsedOpus(info=info, stats=stats, author=author)


def parse_opus_item(item: dict[str, Any]) -> ParsedOpus:
    """把 ``data.item`` 解析成 :class:`ParsedOpus`。"""
    if not isinstance(item, dict) or not item:
        raise ValueError("图文 item 为空")

    opus_id = _first_nonempty(item.get("id_str"), item.get("id"))
    basic = _as_dict(item.get("basic"))
    modules = item.get("modules")

    if isinstance(modules, list):
        parsed = _parse_list_modules(modules, opus_id)
    elif isinstance(modules, dict):
        parsed = _parse_dict_modules(modules, opus_id)
    else:
        raise ValueError("图文 item 缺少 modules")

    info = parsed.info
    title = _first_nonempty(info.title, basic.get("title"))
    dynamic_type_id = info.dynamic_type_id or _as_str(item.get("type"))
    if title != info.title:
        info = OpusInfo(
            opus_id=info.opus_id,
            title=title,
            blocks=info.blocks,
            author=info.author,
            stats=info.stats,
            pub_ts=info.pub_ts,
            cover_url=info.cover_url,
            dynamic_type_id=dynamic_type_id,
            is_forward=info.is_forward,
            forward_origin=info.forward_origin,
        )
    return ParsedOpus(info=info, stats=parsed.stats, author=parsed.author)


# ---------- 文本摘要与消息段 ----------


def format_opus_stats(stats: OpusStats, *, view_label: str = "阅读") -> str:
    """格式化互动数据行。"""
    parts = [
        f"{view_label} {format_count(stats.view)}",
        f"点赞 {format_count(stats.like)}",
        f"评论 {format_count(stats.comment)}",
        f"转发 {format_count(stats.repost)}",
    ]
    return "数据: " + " | ".join(parts)


def format_opus_info(info: OpusInfo) -> str:
    """工具结果 / 日志用的纯文本摘要。"""
    lines = [
        f"「{info.title or '无标题'}」",
        f"图文 ID: {info.opus_id}",
        f"UP主: {info.author.name or '未知'}",
    ]
    published = format_timestamp(info.pub_ts)
    if published:
        lines.append(f"发布时间: {published}")
    lines.append(format_opus_stats(info.stats))
    if info.cover_url:
        lines.append(f"封面: {info.cover_url}")
    if info.images:
        lines.append(f"图片: {len(info.images)} 张")
    lines.append(info.url)
    return "\n".join(lines)


def format_opus_history_message(info: OpusInfo, *, video_status: str = "") -> str:
    """写入历史的可读摘要（含正文文本，便于后续 AI 检索）。"""
    lines = [
        f"[Bilibili 图文] 「{info.title or '无标题'}」",
        f"图文 ID: {info.opus_id}",
        f"UP主: {info.author.name or '未知'}",
    ]
    published = format_timestamp(info.pub_ts)
    if published:
        lines.append(f"发布时间: {published}")
    lines.append(format_opus_stats(info.stats))
    if video_status:
        lines.append(f"视频: {video_status}")
    lines.append(f"图片: {len(info.images)} 张")
    text = format_blocks_text(info.blocks)
    if text:
        lines.extend(["---", text])
    lines.append(info.url)
    return "\n".join(lines)


def format_blocks_text(blocks: tuple[OpusBlock, ...]) -> str:
    """把块序列渲染成纯文本（图片以 ``[图片]`` 占位）。"""
    parts: list[str] = []
    for block in blocks:
        if isinstance(block, TextBlock):
            parts.append(block.text)
        elif isinstance(block, ImageBlock):
            parts.append(f"[图片 x{len(block.urls)}]")
        elif isinstance(block, VideoCardBlock):
            parts.append(f"[视频] {block.title} {block.jump_url}".strip())
        elif isinstance(block, OpusCardBlock):
            parts.append(f"[图文] {block.title} {block.jump_url}".strip())
        else:
            parts.append(f"[卡片] {block.title} {block.jump_url}".strip())
    return "\n\n".join(part for part in parts if part)
