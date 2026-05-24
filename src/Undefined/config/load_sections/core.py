"""Load core config section."""

from __future__ import annotations

# 配置分段加载：按 table 解析 TOML → ctx 字段 dict

import logging
from pathlib import Path
from typing import Any, Optional

from ..coercers import (
    _coerce_bool,
    _coerce_int,
    _coerce_int_list,
    _coerce_str,
    _get_value,
)

logger = logging.getLogger(__name__)


# 加载 [core] table：机器人身份、消息开关、彩蛋、OneBot 连接
def load_core(
    data: dict[str, Any], *, config_path: Optional[Path] = None
) -> dict[str, Any]:
    # [core] 机器人 QQ 与管理员
    bot_qq = _coerce_int(_get_value(data, ("core", "bot_qq"), "BOT_QQ"), 0)
    superadmin_qq = _coerce_int(
        _get_value(data, ("core", "superadmin_qq"), "SUPERADMIN_QQ"), 0
    )
    admin_qqs = _coerce_int_list(_get_value(data, ("core", "admin_qq"), "ADMIN_QQ"))
    forward_proxy = _coerce_int(
        _get_value(data, ("core", "forward_proxy_qq"), "FORWARD_PROXY_QQ"),
        0,
    )
    forward_proxy_qq = forward_proxy if forward_proxy > 0 else None
    # [core] 群聊/私聊/拍一拍处理开关
    process_every_message = _coerce_bool(
        _get_value(
            data,
            ("core", "process_every_message"),
            "PROCESS_EVERY_MESSAGE",
        ),
        True,
    )
    process_private_message = _coerce_bool(
        _get_value(
            data,
            ("core", "process_private_message"),
            "PROCESS_PRIVATE_MESSAGE",
        ),
        True,
    )
    process_poke_message = _coerce_bool(
        _get_value(
            data,
            ("core", "process_poke_message"),
            "PROCESS_POKE_MESSAGE",
        ),
        True,
    )
    # [easter_egg] 关键词回复与复读彩蛋
    keyword_reply_raw = _get_value(
        data,
        ("easter_egg", "keyword_reply_enabled"),
        "KEYWORD_REPLY_ENABLED",
    )
    if keyword_reply_raw is None:
        # 兼容旧配置：历史上放在 [core].keyword_reply_enabled
        keyword_reply_raw = _get_value(
            data,
            ("core", "keyword_reply_enabled"),
            None,
        )
    keyword_reply_enabled = _coerce_bool(keyword_reply_raw, False)
    repeat_enabled = _coerce_bool(
        _get_value(
            data,
            ("easter_egg", "repeat_enabled"),
            "EASTER_EGG_REPEAT_ENABLED",
        ),
        False,
    )
    inverted_question_enabled = _coerce_bool(
        _get_value(
            data,
            ("easter_egg", "inverted_question_enabled"),
            "EASTER_EGG_INVERTED_QUESTION_ENABLED",
        ),
        False,
    )
    repeat_threshold = _coerce_int(
        _get_value(
            data,
            ("easter_egg", "repeat_threshold"),
            "EASTER_EGG_REPEAT_THRESHOLD",
        ),
        3,
    )
    if repeat_threshold < 2:
        repeat_threshold = 2
    if repeat_threshold > 20:
        repeat_threshold = 20
    repeat_cooldown_minutes = _coerce_int(
        _get_value(
            data,
            ("easter_egg", "repeat_cooldown_minutes"),
            "EASTER_EGG_REPEAT_COOLDOWN_MINUTES",
        ),
        60,
    )
    if repeat_cooldown_minutes < 0:
        repeat_cooldown_minutes = 0
    context_recent_messages_limit = _coerce_int(
        _get_value(
            data,
            ("core", "context_recent_messages_limit"),
            "CONTEXT_RECENT_MESSAGES_LIMIT",
        ),
        20,
    )
    if context_recent_messages_limit < 0:
        context_recent_messages_limit = 0

    # [core] AI 请求与 tool_call 重试上限
    ai_request_max_retries = _coerce_int(
        _get_value(
            data,
            ("core", "ai_request_max_retries"),
            "AI_REQUEST_MAX_RETRIES",
        ),
        2,
    )
    if ai_request_max_retries < 0:
        ai_request_max_retries = 0

    missing_tool_call_retries = _coerce_int(
        _get_value(
            data,
            ("core", "missing_tool_call_retries"),
            "MISSING_TOOL_CALL_RETRIES",
        ),
        3,
    )
    if missing_tool_call_retries < 0:
        missing_tool_call_retries = 0

    nagaagent_mode_enabled = _coerce_bool(
        _get_value(
            data,
            ("features", "nagaagent_mode_enabled"),
            "NAGAAGENT_MODE_ENABLED",
        ),
        False,
    )
    # [onebot] WebSocket 连接
    onebot_ws_url = _coerce_str(
        _get_value(data, ("onebot", "ws_url"), "ONEBOT_WS_URL"), ""
    )
    onebot_token = _coerce_str(
        _get_value(data, ("onebot", "token"), "ONEBOT_TOKEN"), ""
    )

    return {
        "bot_qq": bot_qq,
        "superadmin_qq": superadmin_qq,
        "admin_qqs": admin_qqs,
        "forward_proxy_qq": forward_proxy_qq,
        "process_every_message": process_every_message,
        "process_private_message": process_private_message,
        "process_poke_message": process_poke_message,
        "keyword_reply_enabled": keyword_reply_enabled,
        "repeat_enabled": repeat_enabled,
        "inverted_question_enabled": inverted_question_enabled,
        "repeat_threshold": repeat_threshold,
        "repeat_cooldown_minutes": repeat_cooldown_minutes,
        "context_recent_messages_limit": context_recent_messages_limit,
        "ai_request_max_retries": ai_request_max_retries,
        "missing_tool_call_retries": missing_tool_call_retries,
        "nagaagent_mode_enabled": nagaagent_mode_enabled,
        "onebot_ws_url": onebot_ws_url,
        "onebot_token": onebot_token,
    }
