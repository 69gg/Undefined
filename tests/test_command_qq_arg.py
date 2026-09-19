"""测试命令解析层对 @ 提及形式 QQ 号参数的自动归一化。"""

from __future__ import annotations

from Undefined.services.command import (
    CommandDispatcher,
    _normalize_qq_arg,
    _split_command_args,
)


def _dispatcher() -> CommandDispatcher:
    return object.__new__(CommandDispatcher)


# ---------------------------------------------------------------------------
# _normalize_qq_arg
# ---------------------------------------------------------------------------


def test_normalize_plain_digits() -> None:
    assert _normalize_qq_arg("1708213363") == "1708213363"


def test_normalize_at_tag_without_name() -> None:
    assert _normalize_qq_arg("[@1708213363]") == "1708213363"


def test_normalize_at_tag_with_name() -> None:
    assert _normalize_qq_arg("[@1708213363(Null)]") == "1708213363"


def test_normalize_at_tag_with_brace() -> None:
    assert _normalize_qq_arg("[@{1708213363}]") == "1708213363"


def test_normalize_passthrough_non_qq() -> None:
    assert _normalize_qq_arg("g") == "g"
    assert _normalize_qq_arg("--ai") == "--ai"
    assert _normalize_qq_arg("2024/12/01/09:00") == "2024/12/01/09:00"
    assert _normalize_qq_arg("") == ""


def test_split_command_args_keeps_at_name_with_spaces() -> None:
    assert _split_command_args("g [@1708213363(Null User)] -r") == [
        "g",
        "[@1708213363(Null User)]",
        "-r",
    ]


# ---------------------------------------------------------------------------
# parse_command
# ---------------------------------------------------------------------------


def test_parse_command_strips_leading_bot_at() -> None:
    d = _dispatcher()
    cmd = d.parse_command("[@123456(Bot)] /admin add 7777777")
    assert cmd == {"name": "admin", "args": ["add", "7777777"]}


def test_parse_command_keeps_inline_at_normalized() -> None:
    d = _dispatcher()
    cmd = d.parse_command("[@123456(Bot)] /admin add [@1708213363(Null)]")
    assert cmd == {"name": "admin", "args": ["add", "1708213363"]}


def test_parse_command_keeps_inline_at_with_space_name_normalized() -> None:
    d = _dispatcher()
    cmd = d.parse_command("/profile [@1708213363(Null User)] -r")
    assert cmd == {"name": "profile", "args": ["1708213363", "-r"]}


def test_parse_command_multiple_at_args() -> None:
    d = _dispatcher()
    cmd = d.parse_command("/bugfix [@12345(A)] [@67890] 2024/12/01/09:00 now")
    assert cmd == {
        "name": "bugfix",
        "args": ["12345", "67890", "2024/12/01/09:00", "now"],
    }


# ---------------------------------------------------------------------------
# _parse_bugfix_args
# ---------------------------------------------------------------------------


def test_parse_bugfix_args_accepts_at_mentions() -> None:
    """未经 parse_command 归一化的原始参数也应支持 @ 提及形式。"""
    d = _dispatcher()
    parsed = d._parse_bugfix_args(
        ["[@12345(张三)]", "[@67890]", "2024/12/01/09:00", "now"]
    )
    assert not isinstance(parsed, str)
    target_qqs, start_date, end_date, start_str, end_str = parsed
    assert target_qqs == [12345, 67890]
    assert start_str == "2024/12/01/09:00"
    assert end_str == "now"
    assert end_date is not None


def test_parse_bugfix_args_accepts_plain_digits() -> None:
    d = _dispatcher()
    parsed = d._parse_bugfix_args(["12345", "2024/12/01/09:00", "2024/12/02/09:00"])
    assert not isinstance(parsed, str)
    assert parsed[0] == [12345]


def test_parse_bugfix_args_rejects_non_qq_target() -> None:
    d = _dispatcher()
    parsed = d._parse_bugfix_args(["abc", "2024/12/01/09:00", "now"])
    assert isinstance(parsed, str)
    assert "格式错误" in parsed


def test_parse_bugfix_args_requires_at_least_three_args() -> None:
    d = _dispatcher()
    assert isinstance(d._parse_bugfix_args(["12345"]), str)


def test_parse_command_no_at_unchanged() -> None:
    d = _dispatcher()
    cmd = d.parse_command("/profile g -r")
    assert cmd == {"name": "profile", "args": ["g", "-r"]}
