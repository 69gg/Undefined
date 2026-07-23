"""Admin merge, validation, and debug helpers for model parsers."""

from __future__ import annotations

# 模型配置解析：原始 dict → ChatModelConfig 等 dataclass

import logging

from ..admin import load_local_admins
from ..api_modes import API_MODE_OPENAI_CHAT_COMPLETIONS
from ..models import (
    AgentModelConfig,
    ChatModelConfig,
    EmbeddingModelConfig,
    GrokModelConfig,
    SecurityModelConfig,
    VisionModelConfig,
)

# 合并多来源配置
logger = logging.getLogger(__name__)


# 合并多来源配置
def _merge_admins(superadmin_qq: int, admin_qqs: list[int]) -> tuple[int, list[int]]:
    # admins.json 与 config.toml 的 admin_qq 合并，去重后超管必在列表中
    local_admins = load_local_admins()
    all_admins = list(set(admin_qqs + local_admins))
    if superadmin_qq and superadmin_qq not in all_admins:
        all_admins.append(superadmin_qq)
    # 校验必填字段
    return superadmin_qq, all_admins


# 校验必填字段
def _verify_required_fields(
    bot_qq: int,
    superadmin_qq: int,
    onebot_ws_url: str,
    chat_model: ChatModelConfig,
    vision_model: VisionModelConfig,
    agent_model: AgentModelConfig,
    knowledge_enabled: bool,
    embedding_model: EmbeddingModelConfig,
) -> None:
    missing: list[str] = []
    if bot_qq <= 0:
        missing.append("core.bot_qq")
    if superadmin_qq <= 0:
        missing.append("core.superadmin_qq")
    if not onebot_ws_url:
        missing.append("onebot.ws_url")
    if not chat_model.api_url:
        missing.append("models.chat.api_url")
    if not chat_model.api_key:
        missing.append("models.chat.api_key")
    if not chat_model.model_name:
        missing.append("models.chat.model_name")
    if not vision_model.api_url:
        missing.append("models.vision.api_url")
    if not vision_model.api_key:
        missing.append("models.vision.api_key")
    if not vision_model.model_name:
        missing.append("models.vision.model_name")
    if not agent_model.api_url:
        missing.append("models.agent.api_url")
    if not agent_model.api_key:
        missing.append("models.agent.api_key")
    if not agent_model.model_name:
        missing.append("models.agent.model_name")
    if knowledge_enabled:
        if not embedding_model.api_url:
            missing.append("models.embedding.api_url")
        if not embedding_model.model_name:
            missing.append("models.embedding.model_name")
    if missing:
        # 输出调试/诊断日志
        raise ValueError(f"缺少必需配置: {', '.join(missing)}")


# 输出调试/诊断日志
def _log_debug_info(
    chat_model: ChatModelConfig,
    vision_model: VisionModelConfig,
    security_model: SecurityModelConfig,
    naga_model: SecurityModelConfig,
    agent_model: AgentModelConfig,
    summary_model: AgentModelConfig,
    grok_model: GrokModelConfig,
) -> None:
    configs: list[
        tuple[
            str,
            ChatModelConfig
            | VisionModelConfig
            | SecurityModelConfig
            | AgentModelConfig
            | GrokModelConfig,
        ]
    ] = [
        ("chat", chat_model),
        ("vision", vision_model),
        ("security", security_model),
        ("naga", naga_model),
        ("agent", agent_model),
        ("summary", summary_model),
        ("grok", grok_model),
    ]
    for name, cfg in configs:
        logger.debug(
            "[配置] %s_model=%s api_url=%s api_key_set=%s api_mode=%s thinking=%s thinking_param=%s reasoning=%s/%s cot_compat=%s responses_tool_choice_compat=%s responses_force_stateless_replay=%s",
            name,
            cfg.model_name,
            cfg.api_url,
            bool(cfg.api_key),
            getattr(cfg, "api_mode", API_MODE_OPENAI_CHAT_COMPLETIONS),
            cfg.thinking_enabled,
            cfg.thinking_param_enabled,
            getattr(cfg, "reasoning_enabled", False),
            getattr(cfg, "reasoning_effort", "medium"),
            getattr(cfg, "thinking_tool_call_compat", False),
            getattr(cfg, "responses_tool_choice_compat", False),
            getattr(cfg, "responses_force_stateless_replay", False),
        )
