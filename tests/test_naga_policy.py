"""Naga 会话级策略与配置迁移测试。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from Undefined.config.models import NagaConfig
from Undefined.config.naga_policy import (
    is_naga_gateway_active_for_group,
    is_naga_gateway_active_for_private,
    is_nagaagent_active_for_group,
    is_nagaagent_active_for_private,
    resolve_naga_session_allowed,
)
from Undefined.config import Config


def _cfg(
    *,
    nagaagent: bool = True,
    naga_enabled: bool = True,
    api_enabled: bool = True,
    mode: str = "off",
    allowed_group_ids: set[int] | None = None,
    blocked_group_ids: set[int] | None = None,
    allowed_private_ids: set[int] | None = None,
    blocked_private_ids: set[int] | None = None,
    superadmin_qq: int = 1,
) -> Any:
    naga = NagaConfig(
        enabled=naga_enabled,
        mode=mode,
        allowed_group_ids=frozenset(allowed_group_ids or set()),
        blocked_group_ids=frozenset(blocked_group_ids or set()),
        allowed_private_ids=frozenset(allowed_private_ids or set()),
        blocked_private_ids=frozenset(blocked_private_ids or set()),
    )
    return SimpleNamespace(
        nagaagent_mode_enabled=nagaagent,
        naga=naga,
        api=SimpleNamespace(enabled=api_enabled),
        superadmin_qq=superadmin_qq,
        is_superadmin=lambda uid: int(uid) == int(superadmin_qq) and superadmin_qq > 0,
    )


def test_naga_config_mode_off_allows_all() -> None:
    naga = NagaConfig(mode="off", blocked_group_ids=frozenset({1}))
    assert naga.is_group_allowed(1)
    assert naga.is_private_allowed(99)


def test_naga_config_blacklist() -> None:
    naga = NagaConfig(
        mode="blacklist",
        blocked_group_ids=frozenset({10}),
        blocked_private_ids=frozenset({20}),
    )
    assert naga.group_denied_reason(10) == "blacklist"
    assert naga.is_group_allowed(11)
    assert naga.private_denied_reason(20) == "blacklist"
    assert naga.is_private_allowed(21)
    assert naga.is_private_allowed(20, is_superadmin=True)


def test_naga_config_allowlist_empty_denies_all() -> None:
    naga = NagaConfig(mode="allowlist")
    assert not naga.is_group_allowed(123)
    assert naga.group_denied_reason(123) == "allowlist"
    assert not naga.is_private_allowed(456)
    assert naga.private_denied_reason(456) == "allowlist"
    # superadmin 仍可绕过私聊空名单
    assert naga.is_private_allowed(456, is_superadmin=True)


def test_naga_config_allowlist_restricts_when_nonempty() -> None:
    naga = NagaConfig(
        mode="allowlist",
        allowed_group_ids=frozenset({100}),
        allowed_private_ids=frozenset({200}),
    )
    assert naga.is_group_allowed(100)
    assert not naga.is_group_allowed(101)
    assert naga.is_private_allowed(200)
    assert not naga.is_private_allowed(201)
    assert naga.is_private_allowed(201, is_superadmin=True)


def test_nagaagent_master_gate() -> None:
    cfg = _cfg(nagaagent=False, mode="off")
    assert not is_nagaagent_active_for_group(cfg, 1)
    assert not is_nagaagent_active_for_private(cfg, 1)


def test_nagaagent_session_allowlist() -> None:
    cfg = _cfg(mode="allowlist", allowed_group_ids={42}, allowed_private_ids={7})
    assert is_nagaagent_active_for_group(cfg, 42)
    assert not is_nagaagent_active_for_group(cfg, 99)
    assert is_nagaagent_active_for_private(cfg, 7)
    assert not is_nagaagent_active_for_private(cfg, 8)
    assert is_nagaagent_active_for_private(cfg, 1)  # superadmin


def test_field_based_fallback_when_helpers_missing() -> None:
    """duck-typed naga 无 is_*_allowed 时按字段判定，且 allowlist 空名单 fail closed。"""
    cfg = SimpleNamespace(
        nagaagent_mode_enabled=True,
        superadmin_qq=0,
        is_superadmin=lambda _uid: False,
        naga=SimpleNamespace(
            mode="allowlist",
            allowed_group_ids=frozenset({10}),
            blocked_group_ids=frozenset(),
            allowed_private_ids=frozenset({20}),
            blocked_private_ids=frozenset(),
        ),
    )
    assert is_nagaagent_active_for_group(cfg, 10)
    assert not is_nagaagent_active_for_group(cfg, 11)
    assert is_nagaagent_active_for_private(cfg, 20)
    assert not is_nagaagent_active_for_private(cfg, 21)

    empty = SimpleNamespace(
        nagaagent_mode_enabled=True,
        superadmin_qq=0,
        is_superadmin=lambda _uid: False,
        naga=SimpleNamespace(
            mode="allowlist",
            allowed_group_ids=frozenset(),
            blocked_group_ids=frozenset(),
            allowed_private_ids=frozenset(),
            blocked_private_ids=frozenset(),
        ),
    )
    assert not is_nagaagent_active_for_group(empty, 1)
    assert not is_nagaagent_active_for_private(empty, 1)

    unknown = SimpleNamespace(
        nagaagent_mode_enabled=True,
        superadmin_qq=0,
        is_superadmin=lambda _uid: False,
        naga=SimpleNamespace(
            mode="weird",
            allowed_group_ids=frozenset({1}),
            blocked_group_ids=frozenset(),
            allowed_private_ids=frozenset({1}),
            blocked_private_ids=frozenset(),
        ),
    )
    assert not is_nagaagent_active_for_group(unknown, 1)
    assert not is_nagaagent_active_for_private(unknown, 1)


def test_naga_gateway_requires_all_masters() -> None:
    cfg = _cfg(nagaagent=True, naga_enabled=True, api_enabled=False)
    assert not is_naga_gateway_active_for_group(cfg, 1)
    cfg2 = _cfg(nagaagent=True, naga_enabled=False, api_enabled=True)
    assert not is_naga_gateway_active_for_private(cfg2, 1)
    cfg3 = _cfg(nagaagent=True, naga_enabled=True, api_enabled=True, mode="off")
    assert is_naga_gateway_active_for_group(cfg3, 1)


def test_resolve_naga_session_allowed() -> None:
    cfg = _cfg(mode="allowlist", allowed_group_ids={5}, allowed_private_ids={9})
    assert resolve_naga_session_allowed(
        cfg, request_type="group", group_id=5, user_id=1
    )
    assert not resolve_naga_session_allowed(
        cfg, request_type="group", group_id=6, user_id=1
    )
    assert resolve_naga_session_allowed(
        cfg, request_type="private", group_id=None, user_id=9
    )
    assert not resolve_naga_session_allowed(
        cfg, request_type="private", group_id=None, user_id=8
    )


def test_legacy_allowed_groups_migration(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[features]
nagaagent_mode_enabled = true

[naga]
enabled = true
allowed_groups = [111, 222]
""",
        encoding="utf-8",
    )
    cfg = Config.load(config_path, strict=False)
    assert cfg.naga.mode == "allowlist"
    assert cfg.naga.allowed_group_ids == frozenset({111, 222})
    assert is_nagaagent_active_for_group(cfg, 111)
    assert not is_nagaagent_active_for_group(cfg, 333)


def test_new_mode_fields_parse(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[naga]
enabled = true
mode = "blacklist"
blocked_group_ids = [10]
blocked_private_ids = [20]
allowed_group_ids = [999]
""",
        encoding="utf-8",
    )
    cfg = Config.load(config_path, strict=False)
    assert cfg.naga.mode == "blacklist"
    assert cfg.naga.blocked_group_ids == frozenset({10})
    assert cfg.naga.blocked_private_ids == frozenset({20})
    # blacklist ignores allowed_*
    assert cfg.naga.is_group_allowed(999)
    assert not cfg.naga.is_group_allowed(10)


def test_invalid_mode_falls_back_to_off(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[naga]
mode = "weird"
blocked_group_ids = [1]
""",
        encoding="utf-8",
    )
    cfg = Config.load(config_path, strict=False)
    assert cfg.naga.mode == "off"
    assert cfg.naga.is_group_allowed(1)
