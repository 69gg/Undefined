"""Config 加载：[easter_egg] repeat_enabled / inverted_question_enabled"""

from __future__ import annotations

from pathlib import Path

from Undefined.config.loader import Config


def _load(tmp_path: Path, text: str) -> Config:
    p = tmp_path / "config.toml"
    p.write_text(text, "utf-8")
    return Config.load(p, strict=False)


_MINIMAL = """
[onebot]
ws_url = "ws://127.0.0.1:3001"
[models.chat]
api_url = "https://api.example/v1"
api_key = "sk-test"
model_name = "gpt-test"
"""


def test_repeat_defaults_to_false(tmp_path: Path) -> None:
    cfg = _load(tmp_path, _MINIMAL)
    assert cfg.repeat_enabled is False
    assert cfg.inverted_question_enabled is False
    assert cfg.repeat_cooldown_minutes == 60


def test_repeat_enabled_explicit(tmp_path: Path) -> None:
    cfg = _load(tmp_path, _MINIMAL + "\n[easter_egg]\nrepeat_enabled = true\n")
    assert cfg.repeat_enabled is True
    assert cfg.inverted_question_enabled is False
    assert cfg.repeat_cooldown_minutes == 60


def test_inverted_question_enabled_explicit(tmp_path: Path) -> None:
    cfg = _load(
        tmp_path,
        _MINIMAL
        + "\n[easter_egg]\nrepeat_enabled = true\ninverted_question_enabled = true\n",
    )
    assert cfg.repeat_enabled is True
    assert cfg.inverted_question_enabled is True


def test_inverted_question_without_repeat(tmp_path: Path) -> None:
    cfg = _load(
        tmp_path,
        _MINIMAL + "\n[easter_egg]\ninverted_question_enabled = true\n",
    )
    assert cfg.repeat_enabled is False
    assert cfg.inverted_question_enabled is True


def test_keyword_reply_still_parsed_from_easter_egg(tmp_path: Path) -> None:
    cfg = _load(
        tmp_path,
        _MINIMAL + "\n[easter_egg]\nkeyword_reply_enabled = true\n",
    )
    assert cfg.keyword_reply_enabled is True


def test_repeat_cooldown_custom_value(tmp_path: Path) -> None:
    cfg = _load(
        tmp_path,
        _MINIMAL + "\n[easter_egg]\nrepeat_cooldown_minutes = 30\n",
    )
    assert cfg.repeat_cooldown_minutes == 30


def test_repeat_cooldown_negative_clamped_to_zero(tmp_path: Path) -> None:
    cfg = _load(
        tmp_path,
        _MINIMAL + "\n[easter_egg]\nrepeat_cooldown_minutes = -5\n",
    )
    assert cfg.repeat_cooldown_minutes == 0
