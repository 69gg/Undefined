from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from Undefined.skills.http_client import request_with_retry
from Undefined.skills.http_config import build_url

logger = logging.getLogger(__name__)


def _coerce_result_limit(value: Any) -> int:
    try:
        limit = int(value)
    except (TypeError, ValueError):
        limit = 5
    return min(10, max(1, limit))


def _get_runtime_config(context: dict[str, Any]) -> Any | None:
    runtime_config = context.get("runtime_config")
    if runtime_config is not None:
        return runtime_config
    ai_client = context.get("ai_client")
    return getattr(ai_client, "runtime_config", None) if ai_client is not None else None


def _build_headers(api_key: str) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def _string_value(value: Any) -> str:
    return str(value or "").strip()


def _format_firecrawl_results(items: list[Any], limit: int) -> str:
    lines: list[str] = ["Firecrawl 搜索结果:"]
    count = 0
    for index, item in enumerate(items[:limit], start=1):
        if not isinstance(item, dict):
            continue
        title = _string_value(item.get("title")) or "无标题"
        url = _string_value(item.get("url"))
        description = _string_value(item.get("description"))
        category = _string_value(item.get("category"))
        position = item.get("position", index)

        lines.append(f"{index}. {title}")
        if url:
            lines.append(f"   URL: {url}")
        if description:
            lines.append(f"   摘要: {description}")
        if category:
            lines.append(f"   分类: {category}")
        if position:
            lines.append(f"   排名: {position}")
        count += 1

    if count == 0:
        return "Firecrawl 搜索未返回结果"
    return "\n".join(lines)


def _extract_error_message(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    for key in ("error", "message"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


async def execute(args: dict[str, Any], context: dict[str, Any]) -> str:
    query = _string_value(args.get("query"))
    if not query:
        return "搜索关键词不能为空"

    runtime_config = _get_runtime_config(context)
    if runtime_config is None:
        return "Firecrawl 搜索功能不可用（缺少运行时配置）"
    if not bool(getattr(runtime_config, "firecrawl_search_enabled", False)):
        return "Firecrawl 搜索功能未启用（search.firecrawl.enabled=false）"

    base_url = _string_value(
        getattr(runtime_config, "firecrawl_base_url", "https://api.firecrawl.dev")
    )
    if not base_url:
        return "Firecrawl 搜索配置不完整：缺少 search.firecrawl.base_url"

    api_key = _string_value(getattr(runtime_config, "firecrawl_api_key", ""))
    limit = _coerce_result_limit(args.get("num_results", 5))
    request_url = build_url(base_url, "/v2/search")
    payload = {"query": query, "limit": limit}

    try:
        response = await request_with_retry(
            "POST",
            request_url,
            json_data=payload,
            headers=_build_headers(api_key),
            default_timeout=30.0,
            context=context,
        )
        data = response.json()
    except json.JSONDecodeError:
        logger.exception("[firecrawl_search] 响应不是合法 JSON")
        return "Firecrawl 搜索失败：响应格式异常"
    except httpx.TimeoutException:
        return "Firecrawl 搜索请求超时，请稍后重试"
    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code
        logger.warning("[firecrawl_search] HTTP 错误: status=%s", status_code)
        if status_code in {401, 403}:
            return "Firecrawl 搜索认证失败，请检查 search.firecrawl.api_key 或 keyless 配额"
        if status_code == 429:
            return "Firecrawl 搜索达到限流或 keyless 配额，请稍后重试或配置 API Key"
        return "Firecrawl 搜索失败：上游服务返回错误"
    except httpx.RequestError:
        logger.exception("[firecrawl_search] 网络请求失败")
        return "Firecrawl 搜索失败：网络请求错误"
    except Exception:
        logger.exception("[firecrawl_search] 搜索失败")
        return "Firecrawl 搜索失败，请稍后重试"

    if not isinstance(data, dict):
        return "Firecrawl 搜索失败：响应格式异常"
    if data.get("success") is False:
        message = _extract_error_message(data)
        return f"Firecrawl 搜索失败：{message}" if message else "Firecrawl 搜索失败"

    result_data = data.get("data")
    web_results = result_data.get("web") if isinstance(result_data, dict) else None
    if not isinstance(web_results, list) or not web_results:
        return "Firecrawl 搜索未返回结果"

    return _format_firecrawl_results(web_results, limit)
