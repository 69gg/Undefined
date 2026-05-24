"""Load access config section."""

from __future__ import annotations

# 配置分段加载：按 table 解析 TOML → ctx 字段 dict

import logging
from pathlib import Path
from typing import Any, Optional

from ..coercers import (
    _coerce_bool,
    _coerce_int_list,
    _coerce_str,
    _get_value,
)

logger = logging.getLogger(__name__)


def load_access(
    data: dict[str, Any], *, config_path: Optional[Path] = None
) -> dict[str, Any]:
    access_mode_raw = _get_value(data, ("access", "mode"), "ACCESS_MODE")
    allowed_group_ids = _coerce_int_list(
        _get_value(data, ("access", "allowed_group_ids"), "ALLOWED_GROUP_IDS")
    )
    blocked_group_ids = _coerce_int_list(
        _get_value(data, ("access", "blocked_group_ids"), "BLOCKED_GROUP_IDS")
    )
    allowed_private_ids = _coerce_int_list(
        _get_value(data, ("access", "allowed_private_ids"), "ALLOWED_PRIVATE_IDS")
    )
    blocked_private_ids = _coerce_int_list(
        _get_value(data, ("access", "blocked_private_ids"), "BLOCKED_PRIVATE_IDS")
    )
    superadmin_bypass_allowlist = _coerce_bool(
        _get_value(
            data,
            ("access", "superadmin_bypass_allowlist"),
            "SUPERADMIN_BYPASS_ALLOWLIST",
        ),
        True,
    )
    superadmin_bypass_private_blacklist = _coerce_bool(
        _get_value(
            data,
            ("access", "superadmin_bypass_private_blacklist"),
            "SUPERADMIN_BYPASS_PRIVATE_BLACKLIST",
        ),
        False,
    )
    if access_mode_raw is None:
        # 兼容旧配置：未配置 mode 时沿用历史行为（群黑名单 + 白名单联动）。
        if (
            allowed_group_ids
            or blocked_group_ids
            or allowed_private_ids
            or blocked_private_ids
        ):
            access_mode = "legacy"
            logger.warning(
                "[配置] access.mode 未设置，已启用兼容模式（legacy）。建议显式设置为 off/blacklist/allowlist。"
            )
        # 否则分支
        else:
            access_mode = "off"
    # 否则分支
    else:
        access_mode = _coerce_str(access_mode_raw, "off").lower()
        if access_mode not in {"off", "blacklist", "allowlist"}:
            logger.warning(
                "[配置] access.mode 非法（仅支持 off/blacklist/allowlist），已回退为 off: %s",
                access_mode,
            )
            access_mode = "off"

    return {
        "allowed_group_ids": allowed_group_ids,
        "blocked_group_ids": blocked_group_ids,
        "allowed_private_ids": allowed_private_ids,
        "blocked_private_ids": blocked_private_ids,
        "superadmin_bypass_allowlist": superadmin_bypass_allowlist,
        "superadmin_bypass_private_blacklist": superadmin_bypass_private_blacklist,
        "access_mode": access_mode,
    }
