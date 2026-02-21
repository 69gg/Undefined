"""parse_command 的 @ 清洗正则极端测试"""

import pytest
from unittest.mock import MagicMock

from Undefined.services.command import CommandDispatcher


@pytest.fixture()
def dispatcher() -> CommandDispatcher:
    stub = MagicMock()
    return CommandDispatcher(
        config=stub,
        sender=stub,
        ai=stub,
        faq_storage=stub,
        onebot=stub,
        security=stub,
    )


@pytest.mark.parametrize(
    "text, expected_name",
    [
        # 基本场景
        ("/help", "help"),
        ("[@123] /help", "help"),
        ("[@123(test)] /help", "help"),
        # 昵称含特殊字符
        ("[@123(na]me)] /help", "help"),
        ("[@123([test])] /help", "help"),
        ("[@123(@test)] /help", "help"),
        ("[@123([@foo])] /help", "help"),
        # 昵称含闭合序列 )]
        ("[@123(a)]b)] /help", "help"),
        ("[@123(x)](y)] /help", "help"),
        # 多个 @ 段
        ("[@11(a)] [@22(b)] /stats 7d", "stats"),
        ("[@11(a)]b)] [@22(c)] /help", "help"),
    ],
    ids=[
        "bare_cmd",
        "at_no_name",
        "at_simple_name",
        "name_with_bracket",
        "name_with_brackets",
        "name_with_at",
        "name_with_at_bracket",
        "name_with_close_seq",
        "name_with_close_seq_paren",
        "multi_at",
        "multi_at_close_seq",
    ],
)
def test_parse_command_recognises(
    dispatcher: CommandDispatcher, text: str, expected_name: str
) -> None:
    result = dispatcher.parse_command(text)
    assert result is not None, f"未能识别命令: {text!r}"
    assert result["name"] == expected_name


@pytest.mark.parametrize(
    "text",
    [
        "普通文本",
        "[@123] 普通聊天",
        "[@123(name)] 不是命令",
        "",
    ],
    ids=["plain", "at_no_cmd", "at_name_no_cmd", "empty"],
)
def test_parse_command_returns_none(dispatcher: CommandDispatcher, text: str) -> None:
    assert dispatcher.parse_command(text) is None
