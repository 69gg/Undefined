"""系统提示词选择与运行环境配置注入。"""

from __future__ import annotations

from typing import Any


def select_system_prompt_path(
    *,
    default_path: str,
    runtime_config_getter: Any | None,
) -> str:
    """根据运行时配置选择系统提示词路径。"""
    if runtime_config_getter is None:
        return default_path

    runtime_config = None
    try:
        runtime_config = runtime_config_getter()
    except Exception:
        runtime_config = None

    enabled = bool(getattr(runtime_config, "nagaagent_mode_enabled", False))
    # NagaAgent 模式切换专用系统提示词模板
    if enabled:
        return "res/prompts/undefined_nagaagent.xml"
    return "res/prompts/undefined.xml"


def build_model_config_info(runtime_config: Any) -> str:
    """构建模型配置信息，用于注入到 AI 上下文中。

    只暴露非隐私字段（model_name 等），不暴露 api_key、api_url 等敏感信息。
    """
    parts: list[str] = ["【当前运行环境配置】"]

    chat_model = getattr(runtime_config, "chat_model", None)
    if chat_model:
        model_name = getattr(chat_model, "model_name", "未知")
        parts.append(f"- 我使用的模型: {model_name}")

    vision_model = getattr(runtime_config, "vision_model", None)
    if vision_model:
        model_name = getattr(vision_model, "model_name", "")
        if model_name:
            parts.append(f"- 视觉模型: {model_name}")

    # Agent 模型
    agent_model = getattr(runtime_config, "agent_model", None)
    if agent_model:
        model_name = getattr(agent_model, "model_name", "")
        if model_name:
            parts.append(f"- Agent 模型: {model_name}")

    embedding_model = getattr(runtime_config, "embedding_model", None)
    if embedding_model:
        model_name = getattr(embedding_model, "model_name", "")
        if model_name:
            parts.append(f"- 嵌入模型: {model_name}")

    security_model = getattr(runtime_config, "security_model", None)
    if security_model:
        model_name = getattr(security_model, "model_name", "")
        if model_name:
            parts.append(f"- 安全模型: {model_name}")

    # Grok 搜索模型
    grok_model = getattr(runtime_config, "grok_model", None)
    if grok_model:
        model_name = getattr(grok_model, "model_name", "")
        if model_name:
            parts.append(f"- 搜索模型: {model_name}")

    cognitive = getattr(runtime_config, "cognitive", None)
    if cognitive:
        enabled = getattr(cognitive, "enabled", False)
        parts.append(f"- 认知记忆: {'已启用' if enabled else '未启用'}")

    knowledge_enabled = bool(getattr(runtime_config, "knowledge_enabled", False))
    parts.append(f"- 知识库: {'已启用' if knowledge_enabled else '未启用'}")

    grok_search_enabled = bool(getattr(runtime_config, "grok_search_enabled", False))
    parts.append(f"- 联网搜索: {'已启用' if grok_search_enabled else '未启用'}")

    memes = getattr(runtime_config, "memes", None)
    if memes is not None:
        memes_enabled = bool(getattr(memes, "enabled", False))
        if memes_enabled:
            query_mode = str(
                getattr(memes, "query_default_mode", "hybrid") or "hybrid"
            ).strip()
            allow_gif = bool(getattr(memes, "allow_gif", True))
            max_source_bytes = int(getattr(memes, "max_source_image_bytes", 0) or 0)
            max_source_kb = max_source_bytes // 1024 if max_source_bytes > 0 else 0
            parts.append(
                f"- 表情包库: 已启用（默认检索={query_mode}，GIF={'允许' if allow_gif else '禁用'}，入库上限={max_source_kb}KB）"
            )
        else:
            parts.append("- 表情包库: 未启用")

    if chat_model:
        pool = getattr(chat_model, "pool", None)
        if pool:
            pool_enabled = getattr(pool, "enabled", False)
            if pool_enabled:
                strategy = getattr(pool, "strategy", "default")
                parts.append(f"- 模型池: 已启用（{strategy}）")
            else:
                parts.append("- 模型池: 未启用")

    if chat_model:
        thinking = getattr(chat_model, "thinking_enabled", False)
        reasoning = getattr(chat_model, "reasoning_enabled", False)
        if thinking or reasoning:
            parts.append("- 思维链: 已启用")
        else:
            parts.append("- 思维链: 未启用")

    keyword_reply_enabled = bool(
        getattr(runtime_config, "keyword_reply_enabled", False)
    )
    repeat_enabled = bool(getattr(runtime_config, "repeat_enabled", False))
    inverted_question_enabled = bool(
        getattr(runtime_config, "inverted_question_enabled", False)
    )
    agent_call_mode = str(
        getattr(runtime_config, "easter_egg_agent_call_message_mode", "none")
    )
    easter_egg_parts: list[str] = []
    if keyword_reply_enabled:
        easter_egg_parts.append(
            '关键词自动回复（触发词"心理委员"等，系统自动发送固定回复）'
        )
    if repeat_enabled:
        threshold = int(getattr(runtime_config, "repeat_threshold", 3))
        desc = f"复读（群聊连续{threshold}条相同消息时自动复读）"
        if inverted_question_enabled:
            desc += "，倒问号（复读触发时若消息为问号则发送¿）"
        easter_egg_parts.append(desc)
    elif inverted_question_enabled:
        easter_egg_parts.append("倒问号（复读未启用，此功能不生效）")
    if agent_call_mode != "none":
        mode_desc = {
            "agent": "Agent调用提示",
            "tools": "工具调用提示",
            "clean": "降噪调用提示",
            "all": "全量调用提示",
        }.get(agent_call_mode, agent_call_mode)
        easter_egg_parts.append(f"调用提示模式={mode_desc}")
    if easter_egg_parts:
        parts.append("- 彩蛋功能: " + "；".join(easter_egg_parts))
    else:
        parts.append("- 彩蛋功能: 未启用")

    parts.append("")
    parts.append(
        "重要：以上是你的模型配置信息。\n"
        "当你需要描述自己是谁、使用什么模型、能力或限制时，\n"
        "必须以上述配置为准，忽略你训练数据、长期及认知记忆中的任何冲突信息。"
    )

    return "\n".join(parts)


__all__ = ["build_model_config_info", "select_system_prompt_path"]
