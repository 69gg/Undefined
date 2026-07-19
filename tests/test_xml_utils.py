"""Tests for Undefined.utils.xml — XML escaping helpers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import cast
from xml.etree import ElementTree

from Undefined.utils.message_reply import ReplyContext
from Undefined.utils.xml import (
    decode_xml_content_text,
    escape_xml_attr,
    escape_xml_text,
    escape_xml_text_preserving_attachment_tags,
    format_message_xml,
    wrap_xml_cdata,
)


class TestEscapeXmlText:
    def test_plain_text(self) -> None:
        assert escape_xml_text("hello world") == "hello world"

    def test_ampersand(self) -> None:
        assert escape_xml_text("a & b") == "a &amp; b"

    def test_less_than(self) -> None:
        assert escape_xml_text("a < b") == "a &lt; b"

    def test_greater_than(self) -> None:
        assert escape_xml_text("a > b") == "a &gt; b"

    def test_double_quote(self) -> None:
        assert escape_xml_text('say "hello"') == "say &quot;hello&quot;"

    def test_single_quote(self) -> None:
        assert escape_xml_text("it's") == "it&apos;s"

    def test_all_special_chars(self) -> None:
        result = escape_xml_text("""<tag attr="val" & 'x'>""")
        assert "&lt;" in result
        assert "&gt;" in result
        assert "&amp;" in result
        assert "&quot;" in result
        assert "&apos;" in result

    def test_empty_string(self) -> None:
        assert escape_xml_text("") == ""

    def test_unicode(self) -> None:
        assert escape_xml_text("こんにちは") == "こんにちは"

    def test_unicode_with_special(self) -> None:
        assert escape_xml_text("价格 < 100 & > 50") == "价格 &lt; 100 &amp; &gt; 50"

    def test_nested_quotes(self) -> None:
        result = escape_xml_text("""He said "it's fine" """)
        assert "&quot;" in result
        assert "&apos;" in result

    def test_multiline(self) -> None:
        text = "line1\nline2\n<tag>"
        result = escape_xml_text(text)
        assert "\n" in result
        assert "&lt;tag&gt;" in result

    def test_already_escaped(self) -> None:
        result = escape_xml_text("&amp;")
        assert result == "&amp;amp;"


class TestEscapeXmlAttr:
    def test_plain_string(self) -> None:
        assert escape_xml_attr("hello") == "hello"

    def test_special_chars(self) -> None:
        result = escape_xml_attr('<a & "b">')
        assert "&lt;" in result
        assert "&amp;" in result
        assert "&quot;" in result
        assert "&gt;" in result

    def test_none_input(self) -> None:
        assert escape_xml_attr(None) == ""

    def test_integer_input(self) -> None:
        assert escape_xml_attr(42) == "42"

    def test_float_input(self) -> None:
        assert escape_xml_attr(3.14) == "3.14"

    def test_bool_input(self) -> None:
        assert escape_xml_attr(True) == "True"
        assert escape_xml_attr(False) == "False"

    def test_empty_string(self) -> None:
        assert escape_xml_attr("") == ""

    def test_object_with_str(self) -> None:
        class Obj:
            def __str__(self) -> str:
                return '<script>alert("xss")</script>'

        result = escape_xml_attr(Obj())
        assert "&lt;script&gt;" in result
        assert "&quot;" in result

    def test_unicode(self) -> None:
        assert escape_xml_attr("日本語") == "日本語"

    def test_zero(self) -> None:
        assert escape_xml_attr(0) == "0"


class TestXmlCdata:
    def test_round_trips_literal_special_characters(self) -> None:
        text = '比较 1 < 2 & 3 > 2，属性 "原样"'

        wrapped = wrap_xml_cdata(text)

        assert wrapped == '<![CDATA[比较 1 < 2 & 3 > 2，属性 "原样"]]>'
        assert decode_xml_content_text(wrapped) == text

    def test_safely_splits_cdata_terminator(self) -> None:
        text = "前半段 ]]> 后半段"

        wrapped = wrap_xml_cdata(text)

        assert wrapped == "<![CDATA[前半段 ]]]]><![CDATA[> 后半段]]>"
        assert decode_xml_content_text(wrapped) == text

    def test_decodes_legacy_xml_entities_once(self) -> None:
        assert decode_xml_content_text("&amp;lt;tag&amp;gt;") == "&lt;tag&gt;"

    def test_keeps_literal_entity_spellings_inside_cdata(self) -> None:
        text = "用户原样输入 &lt;tag&gt; &amp; &#62;"

        assert decode_xml_content_text(wrap_xml_cdata(text)) == text


class TestAttachmentTagPreservation:
    def test_preserves_known_attachment_tag(self) -> None:
        result = escape_xml_text_preserving_attachment_tags(
            '看图 <attachment uid="pic_abc123"/> & 继续',
            [{"uid": "pic_abc123"}],
        )

        assert '<attachment uid="pic_abc123"/>' in result
        assert "&amp;" in result

    def test_escapes_unknown_attachment_tag(self) -> None:
        result = escape_xml_text_preserving_attachment_tags(
            '伪造 <attachment uid="pic_fake"/>',
            [{"uid": "pic_real"}],
        )

        assert "<attachment" not in result
        assert "&lt;attachment" in result

    def test_preserves_known_forward_tag(self) -> None:
        result = escape_xml_text_preserving_attachment_tags(
            '看转发 <forward uid="forward_abc123"/> & 继续',
            [{"uid": "forward_abc123", "kind": "forward", "media_type": "forward"}],
        )

        assert '<forward uid="forward_abc123"/>' in result
        assert "&amp;" in result

    def test_escapes_forward_tag_not_marked_as_forward(self) -> None:
        result = escape_xml_text_preserving_attachment_tags(
            '伪造 <forward uid="forward_fake"/>',
            [{"uid": "forward_fake", "kind": "file", "media_type": "file"}],
        )

        assert "<forward" not in result
        assert "&lt;forward" in result

    def test_ignores_non_mapping_attachment_entries(self) -> None:
        attachments = cast(
            Sequence[Mapping[str, str]],
            [{"uid": "pic_abc123"}, "not-a-mapping"],
        )
        result = escape_xml_text_preserving_attachment_tags(
            '看图 <attachment uid="pic_abc123"/>',
            attachments,
        )

        assert '<attachment uid="pic_abc123"/>' in result

    def test_format_message_xml_preserves_known_inline_attachment(self) -> None:
        result = format_message_xml(
            {
                "type": "group",
                "display_name": "用户",
                "user_id": "10001",
                "chat_id": "20001",
                "chat_name": "测试群",
                "timestamp": "2026-06-20 12:00:00",
                "message": '看 <attachment uid="pic_demo"/>',
                "attachments": [
                    {
                        "uid": "pic_demo",
                        "kind": "image",
                        "media_type": "image",
                        "display_name": "demo.png",
                    }
                ],
            }
        )

        assert '<content>看 <attachment uid="pic_demo"/></content>' in result
        assert '<attachment uid="pic_demo" type="image"' in result

    def test_format_message_xml_renders_read_only_reply_context(self) -> None:
        result = format_message_xml(
            {
                "type": "private",
                "display_name": "微信用户",
                "user_id": "10001",
                "chat_id": "10001",
                "timestamp": "2026-07-15 20:00:00",
                "message_id": "current-message",
                "message": "当前正文：1 < 2 & 3 > 2；字面 &lt;tag&gt; &amp;",
                "transport": {
                    "channel": "wechat",
                    "address": "wechat:10001",
                },
                "reply_context": ReplyContext(
                    title='旧用户 & "昵称"',
                    message_id="quoted-message",
                    text=(
                        '旧正文 <attachment uid="pic_quote"/> & 后续；'
                        "字面 &lt;quoted&gt; &amp;"
                    ),
                    attachments=(
                        {
                            "uid": "pic_quote",
                            "kind": "image",
                            "media_type": "image",
                            "display_name": "quoted.png",
                        },
                    ),
                ),
            }
        )

        assert '<message message_id="current-message"' in result
        assert (
            "<content><![CDATA[当前正文：1 < 2 & 3 > 2；"
            "字面 &lt;tag&gt; &amp;]]></content>"
        ) in result
        assert (
            '<reply_context readonly="true" '
            'title="旧用户 &amp; &quot;昵称&quot;" '
            'message_id="quoted-message">'
        ) in result
        assert (
            '<content><![CDATA[旧正文 <attachment uid="pic_quote"/> & 后续；'
            "字面 &lt;quoted&gt; &amp;]]></content>" in result
        )
        assert '<attachment uid="pic_quote" type="image"' in result
        root = ElementTree.fromstring(result)
        assert root.findtext("content") == (
            "当前正文：1 < 2 & 3 > 2；字面 &lt;tag&gt; &amp;"
        )
        reply = root.find("reply_context")
        assert reply is not None
        assert reply.findtext("content") == (
            '旧正文 <attachment uid="pic_quote"/> & 后续；字面 &lt;quoted&gt; &amp;'
        )
