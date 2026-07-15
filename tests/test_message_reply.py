from __future__ import annotations

from Undefined.utils.message_reply import (
    ReplyContext,
    build_safe_reply_preview,
    format_markdown_reply,
)


def test_reply_context_round_trips_normalized_attachments() -> None:
    context = ReplyContext.from_mapping(
        {
            "title": " 微信用户 ",
            "message_id": 12345,
            "message": " 旧消息 ",
            "attachments": [
                {
                    "uid": "pic_quote",
                    "kind": "image",
                    "media_type": "image",
                    "display_name": "quoted.png",
                    "source_kind": "weixin_ilink",
                },
                {"kind": "file"},
            ],
        }
    )

    assert context == ReplyContext(
        title="微信用户",
        message_id="12345",
        text="旧消息",
        attachments=(
            {
                "uid": "pic_quote",
                "kind": "image",
                "media_type": "image",
                "display_name": "quoted.png",
                "source_kind": "weixin_ilink",
            },
        ),
    )
    assert ReplyContext.from_mapping(context.to_dict()) == context


def test_safe_reply_preview_removes_attachment_ids_and_local_paths() -> None:
    preview = build_safe_reply_preview(
        (
            '旧消息 <attachment uid="pic_quote"/> '
            "[图片 uid=pic_legacy name=/srv/private/legacy.png]\n附件："
        ),
        [
            {
                "uid": "pic_quote",
                "kind": "image",
                "media_type": "image",
                "display_name": "/srv/private/quoted.png",
            }
        ],
    )

    assert preview == "旧消息\n[图片: quoted.png]"
    assert "pic_quote" not in preview
    assert "pic_legacy" not in preview
    assert "/srv/private" not in preview


def test_markdown_reply_quotes_each_preview_line_before_body() -> None:
    context = ReplyContext(
        title="微信 用户",
        text="第一行\n第二行",
    )

    assert format_markdown_reply(context, "当前回复") == (
        "> **引用 微信 用户**\n> 第一行\n> 第二行\n\n当前回复"
    )
