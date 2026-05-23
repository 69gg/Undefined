"""Load logging_tools config section."""

from __future__ import annotations

# 配置分段加载：按 table 解析 TOML → ctx 字段 dict

import logging
import os
import re
from pathlib import Path
from typing import Any, Optional

from ..coercers import (
    _coerce_bool,
    _coerce_int,
    _coerce_str,
    _get_value,
    _warn_env_fallback,
)
from ..domain_parsers import (
    _parse_easter_egg_call_mode,
)

logger = logging.getLogger(__name__)


def load_logging_tools(
    data: dict[str, Any], *, config_path: Optional[Path] = None
) -> dict[str, Any]:
    log_level = _coerce_str(
        _get_value(data, ("logging", "level"), "LOG_LEVEL"), "INFO"
    ).upper()
    log_file_path = _coerce_str(
        _get_value(data, ("logging", "file_path"), "LOG_FILE_PATH"),
        "logs/bot.log",
    )
    log_max_size_mb = _coerce_int(
        _get_value(data, ("logging", "max_size_mb"), "LOG_MAX_SIZE_MB"), 10
    )
    log_backup_count = _coerce_int(
        _get_value(data, ("logging", "backup_count"), "LOG_BACKUP_COUNT"), 5
    )
    log_tty_enabled = _coerce_bool(
        _get_value(data, ("logging", "tty_enabled"), "LOG_TTY_ENABLED"),
        False,
    )
    log_thinking = _coerce_bool(
        _get_value(data, ("logging", "log_thinking"), "LOG_THINKING"), True
    )

    tools_dot_delimiter = _coerce_str(
        _get_value(data, ("tools", "dot_delimiter"), "TOOLS_DOT_DELIMITER"), "-_-"
    ).strip()
    if not tools_dot_delimiter:
        tools_dot_delimiter = "-_-"
    # dot_delimiter 必须满足 OpenAI 兼容的 function.name 约束。
    if "." in tools_dot_delimiter or not re.fullmatch(
        r"[a-zA-Z0-9_-]+", tools_dot_delimiter
    ):
        logger.warning(
            "[配置] tools.dot_delimiter 非法（仅允许 [a-zA-Z0-9_-] 且不能包含 '.'），已回退默认值: '-_-'（当前=%s）",
            tools_dot_delimiter,
        )
        tools_dot_delimiter = "-_-"
    tools_description_max_len = _coerce_int(
        _get_value(data, ("tools", "description_max_len"), "TOOLS_DESCRIPTION_MAX_LEN"),
        1024,
    )
    tools_description_truncate_enabled = _coerce_bool(
        _get_value(
            data,
            ("tools", "description_truncate_enabled"),
            "TOOLS_DESCRIPTION_TRUNCATE_ENABLED",
        ),
        False,
    )
    tools_sanitize_verbose = _coerce_bool(
        _get_value(data, ("tools", "sanitize_verbose"), "TOOLS_SANITIZE_VERBOSE"),
        False,
    )
    tools_description_preview_len = _coerce_int(
        _get_value(
            data,
            ("tools", "description_preview_len"),
            "TOOLS_DESCRIPTION_PREVIEW_LEN",
        ),
        160,
    )

    easter_egg_mode_raw = _get_value(
        data,
        ("easter_egg", "agent_call_message_enabled"),
        "EASTER_EGG_AGENT_CALL_MESSAGE_ENABLED",
    )
    if easter_egg_mode_raw is None:
        easter_egg_mode_raw = os.getenv("EASTER_EGG_AGENT_CALL_MESSAGE_MODE")
        if easter_egg_mode_raw is not None:
            _warn_env_fallback("EASTER_EGG_AGENT_CALL_MESSAGE_MODE")
        # 否则分支
        else:
            easter_egg_mode_raw = os.getenv("EASTER_EGG_CALL_MESSAGE_MODE")
            if easter_egg_mode_raw is not None:
                _warn_env_fallback("EASTER_EGG_CALL_MESSAGE_MODE")

    easter_egg_agent_call_message_mode = _parse_easter_egg_call_mode(
        easter_egg_mode_raw
    )

    return {
        "log_level": log_level,
        "log_file_path": log_file_path,
        "log_max_size": log_max_size_mb * 1024 * 1024,
        "log_backup_count": log_backup_count,
        "log_tty_enabled": log_tty_enabled,
        "log_thinking": log_thinking,
        "tools_dot_delimiter": tools_dot_delimiter,
        "tools_description_max_len": tools_description_max_len,
        "tools_description_truncate_enabled": tools_description_truncate_enabled,
        "tools_sanitize_verbose": tools_sanitize_verbose,
        "tools_description_preview_len": tools_description_preview_len,
        "easter_egg_agent_call_message_mode": easter_egg_agent_call_message_mode,
    }
