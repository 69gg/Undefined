from __future__ import annotations

import logging
from typing import Any

from Undefined.ai.parsing import extract_choices_content

logger = logging.getLogger(__name__)

_SOURCE_CONTAINER_KEYS = (
    "citations",
    "references",
    "annotations",
    "sources",
    "search_results",
    "results",
    "items",
    "data",
    "message",
    "choices",
    "url_citation",
)


def _normalize_query(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _extract_content(result: dict[str, Any]) -> str:
    try:
        return extract_choices_content(result).strip()
    except Exception:
        choice = result.get("choices", [{}])[0]
        if not isinstance(choice, dict):
            return ""
        message = choice.get("message", {})
        if isinstance(message, dict):
            return str(message.get("content") or "").strip()
        return str(choice.get("content") or "").strip()


def _append_source(
    sources: list[tuple[str, str]],
    seen: set[str],
    *,
    url: str,
    title: str,
) -> None:
    normalized_url = str(url or "").strip()
    if not normalized_url.startswith(("http://", "https://")):
        return
    if normalized_url in seen:
        return
    seen.add(normalized_url)
    sources.append((str(title or "").strip(), normalized_url))


def _collect_sources(
    value: Any,
    sources: list[tuple[str, str]],
    seen: set[str],
    *,
    depth: int = 0,
    max_depth: int = 5,
) -> None:
    if depth > max_depth or len(sources) >= 8:
        return

    if isinstance(value, dict):
        _append_source(
            sources,
            seen,
            url=str(value.get("url") or value.get("link") or ""),
            title=str(
                value.get("title")
                or value.get("name")
                or value.get("label")
                or value.get("source")
                or ""
            ),
        )
        for key in _SOURCE_CONTAINER_KEYS:
            if key in value:
                _collect_sources(
                    value[key],
                    sources,
                    seen,
                    depth=depth + 1,
                    max_depth=max_depth,
                )
        return

    if isinstance(value, list):
        for item in value[:20]:
            _collect_sources(
                item,
                sources,
                seen,
                depth=depth + 1,
                max_depth=max_depth,
            )


def _format_sources(result: dict[str, Any]) -> str:
    sources: list[tuple[str, str]] = []
    seen: set[str] = set()
    _collect_sources(result, sources, seen)
    if not sources:
        return ""

    lines = ["", "参考链接:"]
    for title, url in sources:
        if title:
            lines.append(f"- {title}: {url}")
        else:
            lines.append(f"- {url}")
    return "\n".join(lines)


async def execute(args: dict[str, Any], context: dict[str, Any]) -> str:
    query = _normalize_query(args.get("query"))
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

    messages = [
        {
            "role": "system",
            "content": (
                "你是联网搜索工具。上游会自动进行互联网搜索。"
                "请直接回答用户的问题，优先给出结论，再补充关键事实；"
                "如存在不确定性要明确说明；若响应中带有来源链接，请保留可追溯性。"
            ),
        },
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

    content = _extract_content(result)
    if not content:
        return "Grok 搜索未返回有效内容"

    return f"{content}{_format_sources(result)}"
