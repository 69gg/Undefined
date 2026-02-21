from __future__ import annotations

from pathlib import Path

from Undefined.config.loader import Config


def _load_config(tmp_path: Path, access_toml: str) -> Config:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        (
            "[core]\n"
            "bot_qq = 10001\n"
            "superadmin_qq = 20002\n\n"
            "[onebot]\n"
            'ws_url = "ws://127.0.0.1:3001"\n\n'
            "[access]\n"
            f"{access_toml}\n"
        ),
        encoding="utf-8",
    )
    return Config.load(config_path=config_path, strict=False)


def test_group_blacklist_blocks_even_if_in_allowlist(tmp_path: Path) -> None:
    config = _load_config(
        tmp_path,
        (
            "allowed_group_ids = [123456]\n"
            "blocked_group_ids = [123456]\n"
            "allowed_private_ids = []\n"
        ),
    )

    assert config.allowlist_mode_enabled() is True
    assert config.access_control_enabled() is True
    assert config.group_access_denied_reason(123456) == "blacklist"
    assert config.is_group_allowed(123456) is False


def test_group_blacklist_only_does_not_block_private(tmp_path: Path) -> None:
    config = _load_config(
        tmp_path,
        (
            "allowed_group_ids = []\n"
            "blocked_group_ids = [123456]\n"
            "allowed_private_ids = []\n"
        ),
    )

    assert config.allowlist_mode_enabled() is False
    assert config.access_control_enabled() is True
    assert config.is_group_allowed(123456) is False
    assert config.group_access_denied_reason(654321) is None
    assert config.is_private_allowed(30003) is True


def test_private_still_follows_allowlist_mode(tmp_path: Path) -> None:
    config = _load_config(
        tmp_path,
        (
            "allowed_group_ids = [123456]\n"
            "blocked_group_ids = []\n"
            "allowed_private_ids = []\n"
            "superadmin_bypass_allowlist = false\n"
        ),
    )

    assert config.allowlist_mode_enabled() is True
    assert config.private_access_denied_reason(30003) == "allowlist"
    assert config.is_private_allowed(30003) is False
