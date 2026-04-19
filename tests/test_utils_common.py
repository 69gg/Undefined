"""Tests for Undefined.utils.common."""

from __future__ import annotations

from typing import Any

from Undefined.utils.common import (
    FORWARD_EXPAND_MAX_CHARS,
    _format_forward_node_time,
    _normalize_message_content,
    _parse_at_segment,
    _parse_media_segment,
    _parse_segment,
    _truncate_forward_text,
    extract_text,
    matches_xinliweiyuan,
    message_to_segments,
    process_at_mentions,
)


# ---------------------------------------------------------------------------
# extract_text
# ---------------------------------------------------------------------------


class TestExtractText:
    def test_text_segment(self) -> None:
        segments: list[dict[str, Any]] = [{"type": "text", "data": {"text": "hello"}}]
        assert extract_text(segments) == "hello"

    def test_multiple_text_segments_joined(self) -> None:
        segments: list[dict[str, Any]] = [
            {"type": "text", "data": {"text": "hello "}},
            {"type": "text", "data": {"text": "world"}},
        ]
        assert extract_text(segments) == "hello world"

    def test_at_segment_without_name(self) -> None:
        segments: list[dict[str, Any]] = [{"type": "at", "data": {"qq": "123456"}}]
        assert extract_text(segments) == "[@123456]"

    def test_at_segment_with_name(self) -> None:
        segments: list[dict[str, Any]] = [
            {"type": "at", "data": {"qq": "123456", "name": "Bob"}}
        ]
        assert extract_text(segments) == "[@123456(Bob)]"

    def test_face_segment(self) -> None:
        segments: list[dict[str, Any]] = [{"type": "face", "data": {}}]
        assert extract_text(segments) == "[表情]"

    def test_image_segment(self) -> None:
        segments: list[dict[str, Any]] = [{"type": "image", "data": {"file": "a.png"}}]
        assert extract_text(segments) == "[图片: a.png]"

    def test_file_segment(self) -> None:
        segments: list[dict[str, Any]] = [{"type": "file", "data": {"file": "doc.pdf"}}]
        assert extract_text(segments) == "[文件: doc.pdf]"

    def test_video_segment(self) -> None:
        segments: list[dict[str, Any]] = [{"type": "video", "data": {"file": "v.mp4"}}]
        assert extract_text(segments) == "[视频: v.mp4]"

    def test_record_segment(self) -> None:
        segments: list[dict[str, Any]] = [{"type": "record", "data": {"file": "r.amr"}}]
        assert extract_text(segments) == "[语音: r.amr]"

    def test_audio_segment(self) -> None:
        segments: list[dict[str, Any]] = [{"type": "audio", "data": {"file": "a.mp3"}}]
        assert extract_text(segments) == "[音频: a.mp3]"

    def test_forward_segment_with_id(self) -> None:
        segments: list[dict[str, Any]] = [{"type": "forward", "data": {"id": "fw123"}}]
        assert extract_text(segments) == "[合并转发: fw123]"

    def test_forward_segment_without_id(self) -> None:
        segments: list[dict[str, Any]] = [{"type": "forward", "data": {}}]
        assert extract_text(segments) == "[合并转发]"

    def test_reply_segment_with_id(self) -> None:
        segments: list[dict[str, Any]] = [{"type": "reply", "data": {"id": "42"}}]
        assert extract_text(segments) == "[引用: 42]"

    def test_reply_segment_without_id(self) -> None:
        segments: list[dict[str, Any]] = [{"type": "reply", "data": {}}]
        assert extract_text(segments) == "[引用]"

    def test_unknown_segment_skipped(self) -> None:
        segments: list[dict[str, Any]] = [
            {"type": "unknown_custom", "data": {}},
            {"type": "text", "data": {"text": "ok"}},
        ]
        assert extract_text(segments) == "ok"

    def test_empty_segments(self) -> None:
        assert extract_text([]) == ""

    def test_mixed_segments(self) -> None:
        segments: list[dict[str, Any]] = [
            {"type": "text", "data": {"text": "hi "}},
            {"type": "face", "data": {}},
            {"type": "text", "data": {"text": " bye"}},
        ]
        assert extract_text(segments) == "hi [表情] bye"

    def test_data_not_dict_fallback(self) -> None:
        """If data is not a dict, segment should still be handled safely."""
        segments: list[dict[str, Any]] = [
            {"type": "text", "data": "not_a_dict"},
        ]
        # data becomes {}, so text = ""
        assert extract_text(segments) == ""


# ---------------------------------------------------------------------------
# process_at_mentions
# ---------------------------------------------------------------------------


class TestProcessAtMentions:
    def test_basic_at(self) -> None:
        assert process_at_mentions("[@123456]") == "[CQ:at,qq=123456]"

    def test_at_with_braces(self) -> None:
        assert process_at_mentions("[@{123456}]") == "[CQ:at,qq=123456]"

    def test_multiple_ats(self) -> None:
        result = process_at_mentions("[@11111] hi [@22222]")
        assert result == "[CQ:at,qq=11111] hi [CQ:at,qq=22222]"

    def test_escaped_brackets(self) -> None:
        result = process_at_mentions("\\[@123456\\]")
        assert result == "[@123456]"

    def test_no_match(self) -> None:
        assert process_at_mentions("hello world") == "hello world"


# ---------------------------------------------------------------------------
# message_to_segments
# ---------------------------------------------------------------------------


class TestMessageToSegments:
    def test_plain_text_only(self) -> None:
        segs = message_to_segments("hello world")
        assert segs == [{"type": "text", "data": {"text": "hello world"}}]

    def test_cq_at(self) -> None:
        segs = message_to_segments("[CQ:at,qq=123]")
        assert segs == [{"type": "at", "data": {"qq": "123"}}]

    def test_text_around_cq(self) -> None:
        segs = message_to_segments("hi [CQ:face,id=178] bye")
        assert len(segs) == 3
        assert segs[0] == {"type": "text", "data": {"text": "hi "}}
        assert segs[1] == {"type": "face", "data": {"id": "178"}}
        assert segs[2] == {"type": "text", "data": {"text": " bye"}}

    def test_empty_string(self) -> None:
        assert message_to_segments("") == []

    def test_cq_without_args(self) -> None:
        segs = message_to_segments("[CQ:face]")
        assert segs == [{"type": "face", "data": {}}]


# ---------------------------------------------------------------------------
# matches_xinliweiyuan
# ---------------------------------------------------------------------------


class TestMatchesXinliweiyuan:
    def test_exact_keyword(self) -> None:
        assert matches_xinliweiyuan("心理委员") is True

    def test_keyword_with_prefix(self) -> None:
        assert matches_xinliweiyuan("找心理委员") is True

    def test_keyword_with_suffix(self) -> None:
        assert matches_xinliweiyuan("心理委员在吗") is True

    def test_keyword_both_sides_fails(self) -> None:
        assert matches_xinliweiyuan("我找心理委员吧") is False

    def test_no_keyword(self) -> None:
        assert matches_xinliweiyuan("你好世界") is False

    def test_too_many_extra_chars(self) -> None:
        assert matches_xinliweiyuan("abcdef心理委员") is False

    def test_punctuation_not_counted(self) -> None:
        # Punctuation is removed before counting
        assert matches_xinliweiyuan("！！心理委员") is True

    def test_five_chars_suffix(self) -> None:
        assert matches_xinliweiyuan("心理委员abcde") is True

    def test_six_chars_suffix(self) -> None:
        assert matches_xinliweiyuan("心理委员abcdef") is False


# ---------------------------------------------------------------------------
# _normalize_message_content
# ---------------------------------------------------------------------------


class TestNormalizeMessageContent:
    def test_list_of_dicts(self) -> None:
        content: list[dict[str, Any]] = [{"type": "text", "data": {"text": "hi"}}]
        result = _normalize_message_content(content)
        assert result == content

    def test_single_dict(self) -> None:
        seg: dict[str, Any] = {"type": "text", "data": {"text": "hi"}}
        result = _normalize_message_content(seg)
        assert result == [seg]

    def test_string(self) -> None:
        result = _normalize_message_content("hello [CQ:face]")
        assert len(result) == 2
        assert result[0]["type"] == "text"
        assert result[1]["type"] == "face"

    def test_list_with_string_items(self) -> None:
        result = _normalize_message_content(["hello"])
        assert result == [{"type": "text", "data": {"text": "hello"}}]

    def test_unsupported_type_returns_empty(self) -> None:
        result = _normalize_message_content(12345)
        assert result == []


# ---------------------------------------------------------------------------
# _format_forward_node_time
# ---------------------------------------------------------------------------


class TestFormatForwardNodeTime:
    def test_valid_timestamp(self) -> None:
        result = _format_forward_node_time(1700000000)
        assert "2023" in result

    def test_millisecond_timestamp(self) -> None:
        result = _format_forward_node_time(1700000000000)
        assert "2023" in result

    def test_zero_returns_empty(self) -> None:
        assert _format_forward_node_time(0) == ""

    def test_none_returns_empty(self) -> None:
        assert _format_forward_node_time(None) == ""

    def test_empty_string_returns_empty(self) -> None:
        assert _format_forward_node_time("") == ""

    def test_invalid_string_returns_as_is(self) -> None:
        assert _format_forward_node_time("not_a_time") == "not_a_time"


# ---------------------------------------------------------------------------
# _truncate_forward_text
# ---------------------------------------------------------------------------


class TestTruncateForwardText:
    def test_short_text_not_truncated(self) -> None:
        text = "hello"
        assert _truncate_forward_text(text) == text

    def test_long_text_truncated(self) -> None:
        text = "a" * (FORWARD_EXPAND_MAX_CHARS + 100)
        result = _truncate_forward_text(text)
        assert "[合并转发内容过长，已截断]" in result
        assert len(result) <= FORWARD_EXPAND_MAX_CHARS + 50  # marker included


# ---------------------------------------------------------------------------
# _parse_segment / _parse_at_segment / _parse_media_segment
# ---------------------------------------------------------------------------


class TestParseHelpers:
    def test_parse_at_segment_with_nickname(self) -> None:
        result = _parse_at_segment({"qq": "999", "nickname": "Nick"}, bot_qq=0)
        assert result == "[@999(Nick)]"

    def test_parse_at_segment_no_name(self) -> None:
        result = _parse_at_segment({"qq": "999"}, bot_qq=0)
        assert result == "[@999]"

    def test_parse_media_segment_image(self) -> None:
        result = _parse_media_segment("image", {"file": "pic.jpg"})
        assert result == "[图片: pic.jpg]"

    def test_parse_media_segment_unknown(self) -> None:
        result = _parse_media_segment("custom_type", {})
        assert result is None

    def test_parse_segment_missing_type(self) -> None:
        seg: dict[str, Any] = {"data": {"text": "hello"}}
        # type="" → falls through to _parse_media_segment → None
        result = _parse_segment(seg)
        assert result is None
