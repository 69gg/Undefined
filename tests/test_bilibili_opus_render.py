from __future__ import annotations

from typing import Any

import pytest

from Undefined.bilibili.models import (
    ImageBlock,
    LinkCardBlock,
    OpusAuthor,
    OpusCardBlock,
    OpusInfo,
    TextBlock,
    VideoCardBlock,
)
from Undefined.bilibili.opus_render import (
    extract_opus_text,
    format_opus_history_message,
    format_opus_info,
    format_opus_segment,
    format_opus_stats,
    parse_opus_item,
)


def _word(text: str) -> dict[str, Any]:
    return {"type": "TEXT_NODE_TYPE_WORD", "word": {"words": text}}


def _rich(node_type: str, text: str, **extra: Any) -> dict[str, Any]:
    return {
        "type": "TEXT_NODE_TYPE_RICH",
        "rich": {"type": node_type, "orig_text": text, "text": text, **extra},
    }


def _text_para(*nodes: dict[str, Any]) -> dict[str, Any]:
    return {"para_type": 1, "text": {"nodes": list(nodes)}}


def _list_item(nodes: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
    return {"nodes": nodes, **extra}


def _opus_item(paragraphs: list[dict[str, Any]], **overrides: Any) -> dict[str, Any]:
    item: dict[str, Any] = {
        "id_str": "933099353259638816",
        "type": 2,
        "basic": {"title": "基础标题", "uid": 293793435},
        "modules": [
            {"module_type": "MODULE_TYPE_TITLE", "module_title": {"text": "模块标题"}},
            {
                "module_type": "MODULE_TYPE_AUTHOR",
                "module_author": {
                    "mid": 293793435,
                    "name": "测试UP",
                    "face": "//i0.hdslb.com/bfs/face/a.jpg",
                    "pub_ts": 1700000000,
                },
            },
            {
                "module_type": "MODULE_TYPE_CONTENT",
                "module_content": {"paragraphs": paragraphs},
            },
            {
                "module_type": "MODULE_TYPE_STAT",
                "module_stat": {
                    "view": {"count": 12000},
                    "like": {"count": 88},
                    "comment": {"count": 42},
                    "forward": {"count": 3},
                    "coin": {"count": 5},
                    "favorite": {"count": 7},
                },
            },
        ],
    }
    item.update(overrides)
    return item


def test_parse_opus_item_list_modules_basic_fields() -> None:
    parsed = parse_opus_item(_opus_item([_text_para(_word("正文第一段"))]))

    info = parsed.info
    assert info.opus_id == "933099353259638816"
    assert info.title == "模块标题"
    assert info.author.name == "测试UP"
    assert info.author.mid == 293793435
    assert info.author.avatar_url == "https://i0.hdslb.com/bfs/face/a.jpg"
    assert info.pub_ts == 1700000000
    assert info.url == "https://www.bilibili.com/opus/933099353259638816"
    assert info.blocks == (TextBlock("正文第一段"),)
    assert parsed.stats.view == 12000
    assert parsed.stats.repost == 3


def test_parse_opus_item_title_falls_back_to_basic() -> None:
    item = _opus_item([_text_para(_word("hi"))])
    modules = [m for m in item["modules"] if m["module_type"] != "MODULE_TYPE_TITLE"]
    item["modules"] = modules

    assert parse_opus_item(item).info.title == "基础标题"


def test_parse_opus_item_renders_rich_nodes() -> None:
    paragraphs = [
        _text_para(
            _word("看看 "),
            _rich("RICH_TEXT_NODE_TYPE_AT", "@某人"),
            _rich(
                "RICH_TEXT_NODE_TYPE_BV",
                "视频",
                jump_url="//www.bilibili.com/video/BV1xx411c7mD",
            ),
            _rich("RICH_TEXT_NODE_TYPE_EMOJI", ""),
        ),
        _text_para(
            {
                "type": "TEXT_NODE_TYPE_FORMULA",
                "formula": {"latex_content": "a^2+b^2"},
            }
        ),
    ]

    blocks = parse_opus_item(_opus_item(paragraphs)).info.blocks

    assert blocks == (
        TextBlock("看看 @某人视频 (https://www.bilibili.com/video/BV1xx411c7mD)[表情]"),
        TextBlock("$a^2+b^2$"),
    )


def test_parse_opus_item_paragraph_types() -> None:
    paragraphs: list[dict[str, Any]] = [
        {"para_type": 2, "pic": {"pics": [{"url": "//i0.hdslb.com/1.jpg"}]}},
        {"para_type": 3, "line": {}},
        {
            "para_type": 4,
            "blockquote": {
                "text": {
                    "nodes": [
                        _word("引用第一行\n引用第二行"),
                        _word("继续"),
                    ]
                }
            },
        },
        {
            "para_type": 5,
            "list": {
                "style": 1,
                "items": [
                    _list_item([_word("第一项")], order=1, level=0),
                    _list_item([_word("子项")], order=1, level=1),
                ],
            },
        },
        {
            "para_type": 5,
            "list": {
                "style": 2,
                "items": [_list_item([_word("无序项")], level=0)],
            },
        },
        {
            "para_type": 7,
            "code": {"lang": "language-python", "content": "print(1)"},
        },
        {"para_type": 9, "text": {"nodes": [_word("未知但按文本处理")]}},
    ]

    blocks = parse_opus_item(_opus_item(paragraphs)).info.blocks

    assert blocks == (
        ImageBlock(("https://i0.hdslb.com/1.jpg",)),
        TextBlock("———"),
        TextBlock("> 引用第一行\n> 引用第二行继续"),
        TextBlock("1. 第一项\n  1. 子项"),
        TextBlock("- 无序项"),
        TextBlock("```python\nprint(1)\n```"),
        TextBlock("未知但按文本处理"),
    )


def test_parse_opus_item_link_card_types() -> None:
    paragraphs: list[dict[str, Any]] = [
        {
            "para_type": 6,
            "link_card": {
                "card": {
                    "type": "LINK_CARD_TYPE_OPUS",
                    "oid": "1056353752004427792",
                    "opus": {
                        "title": "另一篇图文",
                        "jump_url": "//www.bilibili.com/opus/1056353752004427792",
                        "cover": "//i0.hdslb.com/cover.jpg",
                        "author": {"name": "作者"},
                    },
                }
            },
        },
        {
            "para_type": 6,
            "link_card": {
                "card": {
                    "type": "LINK_CARD_TYPE_UGC",
                    "ugc": {"title": "视频卡片", "bvid": "BV1xx411c7mD"},
                }
            },
        },
        {
            "para_type": 6,
            "link_card": {
                "card": {
                    "type": "LINK_CARD_TYPE_OPUS",
                    "oid": "undefined",
                    "opus": {"jump_url": "https://www.bilibili.com/opus/123456"},
                }
            },
        },
        {
            "para_type": 6,
            "link_card": {
                "card": {
                    "type": "LINK_CARD_TYPE_COMMON",
                    "common": {
                        "title": "活动链接",
                        "jump_url": "//www.bilibili.com/blackboard/x.html",
                    },
                }
            },
        },
        {
            "para_type": 6,
            "link_card": {
                "card": {
                    "type": "LINK_CARD_TYPE_GOODS",
                    "item_null": {"text": "商品已下架"},
                }
            },
        },
        {"para_type": 6, "link_card": {"card": {}}},
    ]

    blocks = parse_opus_item(_opus_item(paragraphs)).info.blocks

    assert blocks[0] == OpusCardBlock(
        opus_id="1056353752004427792",
        title="另一篇图文",
        cover_url="https://i0.hdslb.com/cover.jpg",
        jump_url="https://www.bilibili.com/opus/1056353752004427792",
    )
    assert blocks[1] == VideoCardBlock(bvid="BV1xx411c7mD", title="视频卡片")
    assert blocks[2] == OpusCardBlock(
        opus_id="123456",
        title="链接卡片",
        jump_url="https://www.bilibili.com/opus/123456",
    )
    assert blocks[3] == LinkCardBlock(
        title="活动链接", jump_url="https://www.bilibili.com/blackboard/x.html"
    )
    assert blocks[4] == LinkCardBlock(title="商品已下架")
    assert len(blocks) == 5


def test_parse_opus_item_uses_placeholder_for_empty_body() -> None:
    parsed = parse_opus_item(_opus_item([]))
    assert parsed.info.blocks == (TextBlock("（该图文没有正文内容）"),)


def test_parse_opus_item_rejects_broken_items() -> None:
    with pytest.raises(ValueError):
        parse_opus_item({})
    with pytest.raises(ValueError):
        parse_opus_item({"id_str": "1"})


def test_parse_opus_item_dict_modules() -> None:
    item = {
        "id_str": "967717348014293017",
        "type": 2,
        "basic": {},
        "modules": {
            "module_author": {
                "mid": 1,
                "name": "动态UP",
                "face": "https://i0.hdslb.com/face.jpg",
                "pub_ts": 1724986186,
            },
            "module_dynamic": {
                "type": "DYNAMIC_TYPE_DRAW",
                "desc": {"text": "正文来自 desc"},
                "major": {
                    "type": "MAJOR_TYPE_DRAW",
                    "draw": {
                        "items": [
                            {"src": "//i0.hdslb.com/a.jpg"},
                            {"src": "https://i0.hdslb.com/b.jpg"},
                        ]
                    },
                },
            },
            "module_stat": {"like": {"count": 1}},
        },
    }

    parsed = parse_opus_item(item)

    assert parsed.info.author.name == "动态UP"
    assert parsed.info.pub_ts == 1724986186
    assert parsed.info.dynamic_type_id == "DYNAMIC_TYPE_DRAW"
    assert parsed.info.blocks == (
        TextBlock("正文来自 desc"),
        ImageBlock(("https://i0.hdslb.com/a.jpg", "https://i0.hdslb.com/b.jpg")),
    )
    assert parsed.info.cover_url == "https://i0.hdslb.com/a.jpg"


def test_parse_opus_item_dict_modules_major_archive() -> None:
    item = {
        "id_str": "123",
        "basic": {},
        "modules": {
            "module_author": {"name": "UP"},
            "module_dynamic": {
                "type": "DYNAMIC_TYPE_AV",
                "major": {
                    "type": "MAJOR_TYPE_ARCHIVE",
                    "archive": {
                        "bvid": "BV1xx411c7mD",
                        "title": "投稿视频",
                        "cover": "//i0.hdslb.com/c.jpg",
                        "jump_url": "//www.bilibili.com/video/BV1xx411c7mD",
                    },
                },
            },
        },
    }

    blocks = parse_opus_item(item).info.blocks

    assert blocks == (
        VideoCardBlock(
            bvid="BV1xx411c7mD",
            title="投稿视频",
            cover_url="https://i0.hdslb.com/c.jpg",
            jump_url="https://www.bilibili.com/video/BV1xx411c7mD",
        ),
    )


def test_parse_opus_item_dict_modules_major_opus_summary() -> None:
    """通用动态接口的正文在 major.opus.summary 里（长文只给摘要）。"""
    item = {
        "id_str": "933099353259638816",
        "basic": {},
        "modules": {
            "module_author": {"name": "UP", "pub_ts": 1716092523},
            "module_dynamic": {
                "type": "DYNAMIC_TYPE_DRAW",
                "desc": None,
                "major": {
                    "type": "MAJOR_TYPE_OPUS",
                    "opus": {
                        "title": "摘要标题",
                        "jump_url": "https://www.bilibili.com/opus/933099353259638816",
                        "pics": [{"url": "//i0.hdslb.com/cover.jpg"}],
                        "summary": {
                            "has_more": True,
                            "text": "这是摘要正文",
                            "rich_text_nodes": [
                                {
                                    "orig_text": "这是摘要正文",
                                    "type": "RICH_TEXT_NODE_TYPE_TEXT",
                                }
                            ],
                        },
                    },
                },
            },
        },
    }

    blocks = parse_opus_item(item).info.blocks

    assert blocks == (
        TextBlock("这是摘要正文"),
        ImageBlock(("https://i0.hdslb.com/cover.jpg",)),
        TextBlock("（仅摘要，完整正文请见原文链接）"),
    )


def test_parse_opus_item_major_opus_pointing_to_self_is_not_a_card() -> None:
    """指向自身的 major opus 不能变成嵌套卡片，否则会自引用递归。"""
    item = {
        "id_str": "123456",
        "basic": {},
        "modules": {
            "module_author": {"name": "UP"},
            "module_dynamic": {
                "type": "DYNAMIC_TYPE_DRAW",
                "major": {
                    "type": "MAJOR_TYPE_OPUS",
                    "opus": {
                        "jump_url": "https://www.bilibili.com/opus/123456",
                        "summary": {"text": "正文"},
                    },
                },
            },
        },
    }

    blocks = parse_opus_item(item).info.blocks

    assert blocks == (TextBlock("正文"),)


def test_parse_opus_item_major_opus_pointing_elsewhere_is_a_card() -> None:
    item = {
        "id_str": "123456",
        "basic": {},
        "modules": {
            "module_author": {"name": "UP"},
            "module_dynamic": {
                "type": "DYNAMIC_TYPE_FORWARD",
                "major": {
                    "type": "MAJOR_TYPE_OPUS",
                    "opus": {
                        "jump_url": "https://www.bilibili.com/opus/999999",
                        "title": "另一篇",
                        "summary": {"text": ""},
                    },
                },
            },
        },
    }

    blocks = parse_opus_item(item).info.blocks

    assert blocks == (
        OpusCardBlock(
            opus_id="999999",
            title="另一篇",
            jump_url="https://www.bilibili.com/opus/999999",
        ),
    )


def test_format_opus_stats_and_info() -> None:
    parsed = parse_opus_item(_opus_item([_text_para(_word("正文"))]))
    info = parsed.info

    assert (
        format_opus_stats(info.stats) == "数据: 阅读 1.2万 | 点赞 88 | 评论 42 | 转发 3"
    )
    summary = format_opus_info(info)
    assert "「模块标题」" in summary
    assert "图文 ID: 933099353259638816" in summary
    assert "UP主: 测试UP" in summary
    assert "发布时间: 2023-11-15" in summary
    assert summary.endswith("https://www.bilibili.com/opus/933099353259638816")


def test_format_opus_history_message_includes_body_text() -> None:
    parsed = parse_opus_item(
        _opus_item(
            [
                _text_para(_word("第一段")),
                {
                    "para_type": 2,
                    "pic": {"pics": [{"url": "https://i0.hdslb.com/1.jpg"}]},
                },
            ]
        )
    )

    message = format_opus_history_message(parsed.info, video_status="长度超限")

    assert message.startswith("[Bilibili 图文] 「模块标题」")
    assert "图片: 1 张" in message
    assert "视频: 长度超限" in message
    assert "第一段" in message
    assert "[图片 x1]" in message


# ---------- output_mode=text ----------


def _text_info(body: str, *, parts: int = 1) -> OpusInfo:
    """构造一篇正文为 ``body`` 的图文（parts>1 时按段切开）。

    段落之间会插入 ``\\n\\n``，因此 ``total_chars`` 会略大于 ``len(body)``；
    调用方需要精确字数时用 ``parts=1``。
    """
    if parts == 1:
        blocks: tuple[Any, ...] = (TextBlock(body),)
    else:
        size = max(1, len(body) // parts)
        blocks = tuple(
            TextBlock(body[index : index + size]) for index in range(0, len(body), size)
        )
    return OpusInfo(
        opus_id="933099353259638816",
        title="长文图文",
        blocks=blocks,
        author=OpusAuthor(name="测试UP"),
        pub_ts=1700000000,
    )


def test_text_default_returns_first_1000_chars() -> None:
    info = _text_info("甲" * 2500)

    segment = extract_opus_text(info)

    assert segment.total_chars == 2500
    assert segment.offset == 0
    assert len(segment.text) == 1000
    assert segment.has_more is True
    assert segment.ranges == ((0, 1000),)


def test_text_start_and_end_select_exact_range() -> None:
    info = _text_info("".join(str(index % 10) for index in range(500)))

    segment = extract_opus_text(info, start=120, end=130)

    assert segment.text == "0123456789"
    assert segment.offset == 120
    assert segment.has_more is True


def test_text_start_without_end_uses_limit() -> None:
    info = _text_info("乙" * 5000)

    segment = extract_opus_text(info, start=1000, limit=500)

    assert len(segment.text) == 500
    assert segment.offset == 1000
    assert segment.has_more is True

    tail = extract_opus_text(info, start=4800, limit=500)
    assert len(tail.text) == 200
    assert tail.has_more is False


def test_text_start_beyond_total_returns_empty() -> None:
    info = _text_info("短正文")

    segment = extract_opus_text(info, start=100)

    assert segment.text == ""
    assert segment.total_chars == 3
    assert segment.has_more is False


def test_text_end_before_start_falls_back_to_limit() -> None:
    info = _text_info("丙" * 2000)

    segment = extract_opus_text(info, start=500, end=100, limit=200)

    assert len(segment.text) == 200
    assert segment.offset == 500


def test_text_empty_body() -> None:
    info = OpusInfo(
        opus_id="1",
        title="空",
        blocks=(),
        author=OpusAuthor(),
    )

    segment = extract_opus_text(info)

    assert segment.total_chars == 0
    assert segment.text == ""

    # 空文本块同样被跳过
    blank = OpusInfo(
        opus_id="1",
        title="空",
        blocks=(TextBlock(""),),
        author=OpusAuthor(),
    )
    assert extract_opus_text(blank).total_chars == 0


def test_text_invalid_arguments_raise() -> None:
    info = _text_info("丁" * 100)

    with pytest.raises(ValueError, match="limit 必须大于 0"):
        extract_opus_text(info, limit=0)
    with pytest.raises(ValueError, match="limit 过大"):
        extract_opus_text(info, limit=99999)
    with pytest.raises(ValueError, match="start 不能为负数"):
        extract_opus_text(info, start=-1)
    with pytest.raises(ValueError, match="end 不能为负数"):
        extract_opus_text(info, end=-1)
    with pytest.raises(ValueError, match="keyword 至少"):
        extract_opus_text(info, keyword="丁")
    with pytest.raises(ValueError, match="keyword 过长"):
        extract_opus_text(info, keyword="丁" * 300)


def test_text_keyword_returns_context_windows() -> None:
    info = _text_info("甲" * 500 + "目标词" + "乙" * 500)

    segment = extract_opus_text(info, keyword="目标词")

    assert segment.query == "keyword"
    assert segment.keyword == "目标词"
    assert segment.ranges == ((440, 563),)
    assert segment.text == "甲" * 60 + "目标词" + "乙" * 60


def test_text_keyword_multiple_matches_and_truncation() -> None:
    # 关键词之间距离足够远，上下文不重叠
    body = "".join(f"{'甲' * 200}目标词" for _ in range(7))
    info = _text_info(body)

    segment = extract_opus_text(info, keyword="目标词")

    assert len(segment.ranges) == 5
    assert segment.has_more is True
    assert "片段 2" in segment.text
    assert segment.has_more is True


def test_text_keyword_merges_overlapping_windows() -> None:
    info = _text_info("目标词" + "短" * 20 + "目标词")

    segment = extract_opus_text(info, keyword="目标词")

    assert len(segment.ranges) == 1
    assert segment.has_more is False


def test_text_keyword_not_found() -> None:
    info = _text_info("甲" * 100)

    segment = extract_opus_text(info, keyword="找不到")

    assert segment.text == ""
    assert segment.ranges == ()
    assert segment.total_chars == 100


def test_text_keyword_scans_across_blocks() -> None:
    # 关键词在第二个文本块里也要能找到（块之间会插入 \n\n 分隔）
    info = OpusInfo(
        opus_id="1",
        title="多段",
        blocks=(TextBlock("甲" * 100), TextBlock("乙" * 100 + "目标词")),
        author=OpusAuthor(),
    )

    segment = extract_opus_text(info, keyword="目标词")

    assert len(segment.ranges) == 1
    assert segment.text.endswith("目标词")
    # 片段起点落在第二个块内（第一块 100 字 + 分隔符 \n\n）
    assert segment.offset == 100 + 2 + 100 - 60


def test_format_opus_segment_range_output() -> None:
    info = _text_info("戊" * 3000, parts=3)
    segment = extract_opus_text(info, limit=1000)

    message = format_opus_segment(info, segment)

    assert f"正文共 {segment.total_chars} 字，本次返回 0-1000 字" in message
    assert "可用 start=1000 继续读取" in message
    assert "https://www.bilibili.com/opus/933099353259638816" in message


def test_format_opus_segment_tail_output() -> None:
    info = _text_info("己" * 100)

    message = format_opus_segment(info, extract_opus_text(info))

    assert "本次返回 0-100 字" in message
    assert "（已到正文结尾）" in message


def test_format_opus_segment_keyword_output() -> None:
    info = _text_info("甲" * 100 + "目标词" + "乙" * 100)

    message = format_opus_segment(info, extract_opus_text(info, keyword="目标词"))

    assert "关键词「目标词」命中位置: 40-163" in message
    assert "本次给出 1 个片段" in message
    assert "目标词" in message


def test_format_opus_segment_keyword_miss_output() -> None:
    info = _text_info("庚" * 500)

    message = format_opus_segment(info, extract_opus_text(info, keyword="没有"))

    assert "在正文中没有命中" in message
    assert "正文共 500 字" in message


def test_format_opus_segment_empty_body_output() -> None:
    info = OpusInfo(
        opus_id="1", title="空", blocks=(TextBlock(""),), author=OpusAuthor()
    )

    message = format_opus_segment(info, extract_opus_text(info))

    assert "（该图文没有正文文字）" in message


def test_format_opus_segment_start_beyond_total() -> None:
    info = _text_info("辛" * 100)

    message = format_opus_segment(info, extract_opus_text(info, start=500))

    assert "start=500 已超出正文范围（正文共 100 字）" in message
    assert "---" not in message
