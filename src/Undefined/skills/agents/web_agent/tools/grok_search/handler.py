from __future__ import annotations

from datetime import datetime
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


def _extract_grok_content(result: Any) -> str:
    payload = result
    if isinstance(result, str):
        text = result.strip()
        if not text:
            return result
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return result
    if not isinstance(payload, dict):
        return str(result)

    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return str(result)
    first = choices[0]
    if not isinstance(first, dict):
        return str(result)
    message = first.get("message")
    if not isinstance(message, dict):
        return str(result)
    content = message.get("content")
    if isinstance(content, str):
        return content
    return str(result)


def _build_grok_search_system_prompt(now: datetime | None = None) -> str:
    current_time = (now or datetime.now().astimezone()).isoformat(timespec="seconds")
    return "\n".join(
        [
            "你是联网搜索执行器，必须严格遵守以下规则：",
            f"- 当前基准时间是 {current_time}，判断“今天”“最新”“最近”等相对时间时必须以这个时间为准，不要以模型内部时间为准。",
            "- 必须先调用搜索能力获取外部信息，再组织回答；不要只依赖已有知识。",
            "- 总是调用多个搜索工具或多组搜索查询，从不同角度全方位、深度检索以满足用户要求。",
            "- 不可胡编乱造；无法确认的信息要明确说明不确定或未找到。",
            "- 最终回答必须给出来源，优先包含标题、发布时间或访问时间、URL。",
        ]
    )


async def execute(args: dict[str, Any], context: dict[str, Any]) -> str:
    query = str(args.get("search_request") or args.get("query") or "").strip()
    if not query:
        return "请用 search_request 提供完整的自然语言搜索要求。"

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

    messages = [
        {"role": "system", "content": _build_grok_search_system_prompt()},
        {"role": "user", "content": query},
    ]

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

    return _extract_grok_content(result)
