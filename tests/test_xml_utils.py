"""Tests for Undefined.utils.xml — XML escaping helpers."""

from __future__ import annotations

from Undefined.utils.xml import (
    escape_xml_attr,
    escape_xml_text,
    escape_xml_text_preserving_attachment_tags,
    format_message_xml,
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
