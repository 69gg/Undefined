"""Finalize: validation and debug logging."""

from __future__ import annotations

# 配置分段加载：按 table 解析 TOML → ctx 字段 dict

from typing import Any

from ..model_parsers import _log_debug_info, _verify_required_fields


def load_finalize(ctx: dict[str, Any], *, strict: bool = True) -> None:
    # strict=True（首次启动）校验必填；热重载传 strict=False 跳过以免半写文件误杀
    if strict:
        _verify_required_fields(
            bot_qq=ctx["bot_qq"],
            superadmin_qq=ctx["superadmin_qq"],
            onebot_ws_url=ctx["onebot_ws_url"],
            chat_model=ctx["chat_model"],
            vision_model=ctx["vision_model"],
            agent_model=ctx["agent_model"],
            knowledge_enabled=ctx["knowledge_enabled"],
            embedding_model=ctx["embedding_model"],
        )

    _log_debug_info(
        ctx["chat_model"],
        ctx["vision_model"],
        ctx["security_model"],
        ctx["naga_model"],
        ctx["agent_model"],
        ctx["summary_model"],
        ctx["grok_model"],
    )
