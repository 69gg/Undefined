"""Naga 会话级策略：总闸 + 群/私聊黑白名单组合判定。"""

from __future__ import annotations

from typing import Any


def _naga_cfg(config: Any) -> Any | None:
    return getattr(config, "naga", None)


def _is_superadmin(config: Any, user_id: int | None) -> bool:
    if user_id is None:
        return False
    checker = getattr(config, "is_superadmin", None)
    if callable(checker):
        try:
            return bool(checker(int(user_id)))
        except Exception:
            return False
    superadmin_qq = getattr(config, "superadmin_qq", 0)
    try:
        return int(superadmin_qq) > 0 and int(user_id) == int(superadmin_qq)
    except (TypeError, ValueError):
        return False


def is_nagaagent_master_enabled(config: Any) -> bool:
    """进程总闸：是否开启 NagaAgent AI 能力。"""
    return bool(getattr(config, "nagaagent_mode_enabled", False))


def is_naga_gateway_master_enabled(config: Any) -> bool:
    """进程总闸：是否开启外部网关（含 Runtime API）。"""
    if not is_nagaagent_master_enabled(config):
        return False
    naga = _naga_cfg(config)
    if naga is None or not bool(getattr(naga, "enabled", False)):
        return False
    api_cfg = getattr(config, "api", None)
    return bool(getattr(api_cfg, "enabled", False))


def _coerce_id_set(raw: Any) -> set[int]:
    if raw is None:
        return set()
    try:
        return {int(item) for item in raw}
    except (TypeError, ValueError):
        return set()


def _group_allowed_from_fields(naga: Any, group_id: int) -> bool:
    """当缺少 is_group_allowed 方法时，按 mode + 名单字段判定（不 fail-open）。"""
    mode = str(getattr(naga, "mode", "off") or "off").strip().lower()
    gid = int(group_id)
    if mode == "off":
        return True
    if mode == "blacklist":
        return gid not in _coerce_id_set(getattr(naga, "blocked_group_ids", None))
    if mode == "allowlist":
        allowed = _coerce_id_set(getattr(naga, "allowed_group_ids", None))
        if not allowed:
            return True
        return gid in allowed
    return True


def _private_allowed_from_fields(
    naga: Any, user_id: int, *, is_superadmin: bool
) -> bool:
    """当缺少 is_private_allowed 方法时，按 mode + 名单字段判定（不 fail-open）。"""
    if is_superadmin:
        return True
    mode = str(getattr(naga, "mode", "off") or "off").strip().lower()
    uid = int(user_id)
    if mode == "off":
        return True
    if mode == "blacklist":
        return uid not in _coerce_id_set(getattr(naga, "blocked_private_ids", None))
    if mode == "allowlist":
        allowed = _coerce_id_set(getattr(naga, "allowed_private_ids", None))
        if not allowed:
            return True
        return uid in allowed
    return True


def is_nagaagent_active_for_group(config: Any, group_id: int) -> bool:
    """群聊会话是否启用 NagaAgent AI 能力。"""
    if not is_nagaagent_master_enabled(config):
        return False
    naga = _naga_cfg(config)
    if naga is None:
        return False
    is_allowed = getattr(naga, "is_group_allowed", None)
    if callable(is_allowed):
        return bool(is_allowed(int(group_id)))
    return _group_allowed_from_fields(naga, int(group_id))


def is_nagaagent_active_for_private(config: Any, user_id: int) -> bool:
    """私聊会话是否启用 NagaAgent AI 能力。"""
    if not is_nagaagent_master_enabled(config):
        return False
    naga = _naga_cfg(config)
    if naga is None:
        return False
    is_superadmin = _is_superadmin(config, user_id)
    is_allowed = getattr(naga, "is_private_allowed", None)
    if callable(is_allowed):
        return bool(is_allowed(int(user_id), is_superadmin=is_superadmin))
    return _private_allowed_from_fields(naga, int(user_id), is_superadmin=is_superadmin)


def is_naga_gateway_active_for_group(config: Any, group_id: int) -> bool:
    """群聊会话是否启用 Naga 外部网关。"""
    if not is_naga_gateway_master_enabled(config):
        return False
    return is_nagaagent_active_for_group(config, group_id)


def is_naga_gateway_active_for_private(config: Any, user_id: int) -> bool:
    """私聊会话是否启用 Naga 外部网关。"""
    if not is_naga_gateway_master_enabled(config):
        return False
    return is_nagaagent_active_for_private(config, user_id)


def resolve_naga_session_allowed(
    config: Any,
    *,
    request_type: str | None = None,
    group_id: int | None = None,
    user_id: int | None = None,
) -> bool:
    """按会话上下文判断是否启用 NagaAgent AI。

    - group：优先 group_id
    - private：优先 user_id
    - 未知类型：若有 group_id 按群；否则若有 user_id 按私聊；都没有则仅看总闸
    """
    if not is_nagaagent_master_enabled(config):
        return False

    normalized_type = str(request_type or "").strip().lower()
    if normalized_type == "group" or (normalized_type == "" and group_id is not None):
        if group_id is None:
            return False
        return is_nagaagent_active_for_group(config, int(group_id))

    if normalized_type == "private" or (
        normalized_type == "" and user_id is not None and group_id is None
    ):
        if user_id is None:
            return False
        return is_nagaagent_active_for_private(config, int(user_id))

    if group_id is not None:
        return is_nagaagent_active_for_group(config, int(group_id))
    if user_id is not None:
        return is_nagaagent_active_for_private(config, int(user_id))
    # 无会话上下文时仅看总闸（例如部分非 QQ 入口）
    return True


def resolve_naga_gateway_session_allowed(
    config: Any,
    *,
    request_type: str | None = None,
    group_id: int | None = None,
    user_id: int | None = None,
) -> bool:
    """按会话上下文判断是否启用 Naga 外部网关。"""
    if not is_naga_gateway_master_enabled(config):
        return False
    return resolve_naga_session_allowed(
        config,
        request_type=request_type,
        group_id=group_id,
        user_id=user_id,
    )


__all__ = [
    "is_nagaagent_master_enabled",
    "is_naga_gateway_master_enabled",
    "is_nagaagent_active_for_group",
    "is_nagaagent_active_for_private",
    "is_naga_gateway_active_for_group",
    "is_naga_gateway_active_for_private",
    "resolve_naga_session_allowed",
    "resolve_naga_gateway_session_allowed",
]
