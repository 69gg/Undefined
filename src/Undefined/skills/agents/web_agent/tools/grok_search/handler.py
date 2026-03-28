from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def execute(args: dict[str, Any], context: dict[str, Any]) -> str:
    query = str(args.get("query") or "").strip()
    if not query:
        return "请提供详细的自然语言搜索问题。"

    runtime_config = context.get("runtime_config")
    if runtime_config is None:
        ai_client = context.get("ai_client")
        runtime_config = (
            getattr(ai_client, "runtime_config", None) if ai_client else None
        )

    if runtime_config is None:
        return "Grok 搜索功能不可用（缺少运行时配置）"
    if not bool(getattr(runtime_config, "grok_search_enabled", False)):
        return "Grok 搜索功能未启用（search.grok_search_enabled=false）"

    grok_model = getattr(runtime_config, "grok_model", None)
    if grok_model is None:
        return "Grok 搜索功能不可用（models.grok 未加载）"

    missing = [
        key
        for key in ("api_url", "api_key", "model_name")
        if not str(getattr(grok_model, key, "") or "").strip()
    ]
    if missing:
        return f"Grok 搜索模型配置不完整：缺少 models.grok.{', models.grok.'.join(missing)}"

    ai_client = context.get("ai_client")
    if ai_client is None:
        return "Grok 搜索功能不可用（缺少 AI client）"

    messages = [{"role": "user", "content": query}]

    try:
        result = await ai_client.submit_queued_llm_call(
            model_config=grok_model,
            messages=messages,
            call_type="agent_tool:grok_search",
            max_tokens=getattr(grok_model, "max_tokens", 8192),
        )
    except Exception as exc:
        logger.exception("[grok_search] 搜索失败: %s", exc)
        return "Grok 搜索失败，请稍后重试"

    return str(result)
