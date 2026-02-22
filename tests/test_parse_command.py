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
        # 多个 @ 段
        ("[@11(a)] [@22(b)] /stats 7d", "stats"),
    ],
    ids=[
        "bare_cmd",
        "at_no_name",
        "at_simple_name",
        "name_with_bracket",
        "name_with_brackets",
        "name_with_at",
        "name_with_at_bracket",
        "multi_at",
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
        # 防止贪婪越界：普通文本含 )] 后跟 /cmd 不应误触发
        "[@123(a)] foo )] /help",
        "[@123(name)] 看这个)] /stats",
        "",
    ],
    ids=[
        "plain",
        "at_no_cmd",
        "at_name_no_cmd",
        "trailing_close_seq",
        "trailing_close_seq2",
        "empty",
    ],
)
def test_parse_command_returns_none(dispatcher: CommandDispatcher, text: str) -> None:
    assert dispatcher.parse_command(text) is None
