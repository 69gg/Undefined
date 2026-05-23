"""Load models config section."""

from __future__ import annotations

# 配置分段加载：按 table 解析 TOML → ctx 字段 dict

import logging
from pathlib import Path
from typing import Any, Optional

from ..coercers import (
    _coerce_bool,
    _get_value,
)
from ..model_parsers import (
    _parse_agent_model_config,
    _parse_chat_model_config,
    _parse_grok_model_config,
    _parse_historian_model_config,
    _parse_naga_model_config,
    _parse_security_model_config,
    _parse_summary_model_config,
    _parse_vision_model_config,
)

logger = logging.getLogger(__name__)


def load_models(
    data: dict[str, Any], *, config_path: Optional[Path] = None
) -> dict[str, Any]:
    chat_model = _parse_chat_model_config(data)
    vision_model = _parse_vision_model_config(data)
    security_model_enabled = _coerce_bool(
        _get_value(
            data,
            ("models", "security", "enabled"),
            "SECURITY_MODEL_ENABLED",
        ),
        True,
    )
    # 未单独配置的模型段会回退到 chat/security/agent 等主模型
    security_model = _parse_security_model_config(data, chat_model)
    naga_model = _parse_naga_model_config(data, security_model)
    agent_model = _parse_agent_model_config(data)
    historian_model = _parse_historian_model_config(data, agent_model)
    summary_model, summary_model_configured = _parse_summary_model_config(
        data, agent_model
    )
    grok_model = _parse_grok_model_config(data)

    model_pool_enabled = _coerce_bool(
        _get_value(data, ("features", "pool_enabled"), "MODEL_POOL_ENABLED"), False
    )

    return {
        "chat_model": chat_model,
        "vision_model": vision_model,
        "security_model_enabled": security_model_enabled,
        "security_model": security_model,
        "naga_model": naga_model,
        "agent_model": agent_model,
        "historian_model": historian_model,
        "summary_model": summary_model,
        "summary_model_configured": summary_model_configured,
        "grok_model": grok_model,
        "model_pool_enabled": model_pool_enabled,
    }
