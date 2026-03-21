from __future__ import annotations

import pytest

from Undefined.changelog import (
    ChangelogFormatError,
    get_entry,
    get_latest_entry,
    list_entries,
    parse_changelog_text,
)


def test_parse_changelog_text_parses_multiple_entries() -> None:
    entries = parse_changelog_text(
        """
        ## v3.2.6 Responses 重试修复

        修复 replay-only 状态字段导致的兼容性问题。

            - 过滤 replay-only 状态字段
            - 补充相关测试

        ---

        ## v3.2.5 形象资源更新

        调整项目的展示形象和相关素材引用。

        - 更新形象素材
        - 清理旧引用
        - 同步版本文案
        """
    )

    assert [entry.version for entry in entries] == ["v3.2.6", "v3.2.5"]
    assert entries[0].title == "Responses 重试修复"
    assert entries[0].summary == "修复 replay-only 状态字段导致的兼容性问题。"
    assert entries[0].changes == ("过滤 replay-only 状态字段", "补充相关测试")
    assert entries[1].heading_level == 2


def test_get_entry_normalizes_version_without_v_prefix() -> None:
    entries = parse_changelog_text(
        """
        ## v1.0.0 初始发布

        第一个可用版本。

        - 搭建基础架构
        - 接入 OneBot
        - 提供基础工具
        """
    )

    assert get_entry("1.0.0", entries=entries).version == "v1.0.0"
    assert get_latest_entry(entries=entries).version == "v1.0.0"
    assert list_entries(limit=1, entries=entries)[0].version == "v1.0.0"


def test_parse_changelog_text_preserves_multiline_summary() -> None:
    entries = parse_changelog_text(
        """
        ## v2.0.0 Skills 架构

        第一段摘要。

        第二段摘要。

        - 引入 Skills
        - 增加 CLI
        - 调整队列服务
        """
    )

    assert entries[0].summary == "第一段摘要。\n\n第二段摘要。"


@pytest.mark.parametrize(
    "text, expected_message",
    [
        (
            """
            ## v1.0.0 缺摘要
            - 只有 bullet
            """,
            "缺少摘要",
        ),
        (
            """
            ## v1.0.0 缺变更点

            这里只有摘要。
            """,
            "缺少变更点",
        ),
        (
            """
            ## v1.0.0 标题一

            摘要一。

            - 变更一

            ---

            ## v1.0.0 标题二

            摘要二。

            - 变更二
            """,
            "重复版本",
        ),
    ],
)
def test_parse_changelog_text_rejects_invalid_blocks(
    text: str, expected_message: str
) -> None:
    with pytest.raises(ChangelogFormatError, match=expected_message):
        parse_changelog_text(text)
