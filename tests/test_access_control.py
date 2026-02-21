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


def test_access_mode_off_ignores_lists(tmp_path: Path) -> None:
    config = _load_config(
        tmp_path,
        (
            'mode = "off"\n'
            "allowed_group_ids = [123456]\n"
            "blocked_group_ids = [654321]\n"
            "allowed_private_ids = [111111]\n"
            "blocked_private_ids = [222222]\n"
        ),
    )

    assert config.access_control_enabled() is False
    assert config.is_group_allowed(654321) is True
    assert config.is_private_allowed(222222) is True


def test_access_mode_blacklist_blocks_group_and_private(tmp_path: Path) -> None:
    config = _load_config(
        tmp_path,
        (
            'mode = "blacklist"\n'
            "allowed_group_ids = [123456]\n"
            "blocked_group_ids = [654321]\n"
            "allowed_private_ids = [111111]\n"
            "blocked_private_ids = [222222]\n"
        ),
    )

    assert config.blacklist_mode_enabled() is True
    assert config.access_control_enabled() is True
    assert config.group_access_denied_reason(654321) == "blacklist"
    assert config.private_access_denied_reason(222222) == "blacklist"
    assert config.is_group_allowed(654321) is False
    assert config.is_private_allowed(222222) is False
    assert config.is_group_allowed(123456) is True
    assert config.is_private_allowed(111111) is True


def test_private_blacklist_superadmin_bypass_toggle(tmp_path: Path) -> None:
    blocked = _load_config(
        tmp_path,
        (
            'mode = "blacklist"\n'
            "blocked_group_ids = []\n"
            "blocked_private_ids = [20002]\n"
            "superadmin_bypass_private_blacklist = false\n"
        ),
    )
    bypassed = _load_config(
        tmp_path,
        (
            'mode = "blacklist"\n'
            "blocked_group_ids = []\n"
            "blocked_private_ids = [20002]\n"
            "superadmin_bypass_private_blacklist = true\n"
        ),
    )

    assert blocked.is_private_allowed(20002) is False
    assert blocked.private_access_denied_reason(20002) == "blacklist"
    assert bypassed.is_private_allowed(20002) is True
    assert bypassed.private_access_denied_reason(20002) is None


def test_access_mode_allowlist_blocks_unlisted_targets(tmp_path: Path) -> None:
    config = _load_config(
        tmp_path,
        (
            'mode = "allowlist"\n'
            "allowed_group_ids = [123456]\n"
            "allowed_private_ids = [111111]\n"
            "blocked_group_ids = [654321]\n"
            "blocked_private_ids = [222222]\n"
            "superadmin_bypass_allowlist = false\n"
        ),
    )

    assert config.allowlist_mode_enabled() is True
    assert config.access_control_enabled() is True
    assert config.group_access_denied_reason(654321) == "allowlist"
    assert config.private_access_denied_reason(222222) == "allowlist"
    assert config.is_group_allowed(654321) is False
    assert config.is_private_allowed(222222) is False
    assert config.is_group_allowed(123456) is True
    assert config.is_private_allowed(111111) is True


def test_access_mode_allowlist_private_only_does_not_block_groups(
    tmp_path: Path,
) -> None:
    config = _load_config(
        tmp_path,
        (
            'mode = "allowlist"\n'
            "allowed_group_ids = []\n"
            "allowed_private_ids = [111111]\n"
            "blocked_group_ids = []\n"
            "blocked_private_ids = []\n"
        ),
    )

    assert config.group_access_denied_reason(654321) is None
    assert config.is_group_allowed(654321) is True
    assert config.private_access_denied_reason(222222) == "allowlist"
    assert config.is_private_allowed(222222) is False


def test_missing_mode_keeps_legacy_allowlist_behavior(tmp_path: Path) -> None:
    config = _load_config(
        tmp_path,
        (
            "allowed_group_ids = [123456]\n"
            "allowed_private_ids = [111111]\n"
            "blocked_group_ids = []\n"
            "blocked_private_ids = []\n"
        ),
    )

    assert config.access_mode == "legacy"
    assert config.allowlist_mode_enabled() is True
    assert config.is_group_allowed(123456) is True
    assert config.is_group_allowed(654321) is False
    assert config.is_private_allowed(111111) is True
    assert config.is_private_allowed(222222) is False


def test_missing_mode_keeps_legacy_hybrid_behavior(tmp_path: Path) -> None:
    config = _load_config(
        tmp_path,
        (
            "allowed_group_ids = [123456]\n"
            "allowed_private_ids = [111111]\n"
            "blocked_group_ids = [123456]\n"
            "blocked_private_ids = []\n"
        ),
    )

    assert config.access_mode == "legacy"
    # 兼容旧行为：群聊黑名单优先于白名单。
    assert config.group_access_denied_reason(123456) == "blacklist"
    assert config.is_group_allowed(123456) is False
