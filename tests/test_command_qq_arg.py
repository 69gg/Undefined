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


def test_parse_command_no_at_unchanged() -> None:
    d = _dispatcher()
    cmd = d.parse_command("/profile g -r")
    assert cmd == {"name": "profile", "args": ["g", "-r"]}
