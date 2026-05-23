"""LLM 流式响应聚合与回退判定。

解析 SSE/chunk 事件、合并 delta 与 tool_calls，并在上游不支持流式时
判定是否降级为非流式请求；不持有 HTTP 客户端或模型配置。
"""

from __future__ import annotations

import json
from typing import Any

from openai import APIStatusError

from Undefined.ai.llm.thinking import stringify_thinking
from Undefined.ai.transports import API_MODE_CHAT_COMPLETIONS, API_MODE_RESPONSES

_CHAT_COMPLETIONS_KNOWN_FIELDS: set[str] = {
    "model",
    "messages",
    "audio",
    "metadata",
    "max_completion_tokens",
    "max_tokens",
    "modalities",
    "parallel_tool_calls",
    "prediction",
    "prompt_cache_key",
    "prompt_cache_retention",
    "reasoning_effort",
    "safety_identifier",
    "service_tier",
    "store",
    "temperature",
    "top_p",
    "n",
    "stop",
    "presence_penalty",
    "frequency_penalty",
    "logit_bias",
    "user",
    "response_format",
    "seed",
    "stream",
    "stream_options",
    "tools",
    "tool_choice",
    "logprobs",
    "top_logprobs",
    "verbosity",
    "web_search_options",
}

_RESPONSES_KNOWN_FIELDS: set[str] = {
    "background",
    "context_management",
    "conversation",
    "include",
    "model",
    "input",
    "instructions",
    "max_output_tokens",
    "max_tool_calls",
    "metadata",
    "previous_response_id",
    "prompt",
    "prompt_cache_key",
    "prompt_cache_retention",
    "reasoning",
    "safety_identifier",
    "service_tier",
    "store",
    "temperature",
    "top_p",
    "tools",
    "tool_choice",
    "parallel_tool_calls",
    "stream",
    "stream_options",
    "text",
    "truncation",
    "user",
}

_STREAM_FALLBACK_STATUS_CODES = {400, 404, 405, 422, 501}
_STREAM_FALLBACK_ERROR_MARKERS = (
    "stream",
    "stream_options",
    "streaming",
    "not support",
    "unsupported",
    "unrecognized",
    "unknown parameter",
    "unexpected parameter",
)


def split_chat_completion_params(
    body: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """将请求体拆分为 SDK 已知字段与 extra_body。"""
    known: dict[str, Any] = {}
    extra: dict[str, Any] = {}
    for key, value in body.items():
        if key in _CHAT_COMPLETIONS_KNOWN_FIELDS:
            known[key] = value
        else:
            extra[key] = value
    return known, extra


def split_responses_params(
    body: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """将 Responses 请求体拆分为 SDK 已知字段与 extra_body。"""
    known: dict[str, Any] = {}
    extra: dict[str, Any] = {}
    for key, value in body.items():
        if key in _RESPONSES_KNOWN_FIELDS:
            known[key] = value
        else:
            extra[key] = value
    return known, extra


def without_stream_request_fields(body: dict[str, Any]) -> dict[str, Any]:
    """移除 stream / stream_options 字段，用于流式回退。"""
    stripped = dict(body)
    stripped.pop("stream", None)
    stripped.pop("stream_options", None)
    return stripped


def ensure_chat_stream_usage_options(body: dict[str, Any]) -> None:
    """确保 Chat Completions 流式请求携带 include_usage。"""
    stream_options = body.get("stream_options")
    if stream_options is None:
        body["stream_options"] = {"include_usage": True}
        return
    if isinstance(stream_options, dict) and "include_usage" not in stream_options:
        body["stream_options"] = {**stream_options, "include_usage": True}


def _status_error_text(exc: APIStatusError) -> str:
    parts = [str(exc)]
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        parts.append(json.dumps(body, ensure_ascii=False, default=str))
    elif body is not None:
        parts.append(str(body))
    response = getattr(exc, "response", None)
    if response is not None:
        try:
            parts.append(response.text)
        except Exception:
            pass
    return "\n".join(part for part in parts if part).lower()


def should_fallback_from_stream(exc: Exception) -> bool:
    """判定流式失败是否应降级为非流式重试。"""
    if isinstance(exc, NotImplementedError):
        return True
    if not isinstance(exc, APIStatusError):
        return False
    # 仅对明确的 stream 参数/能力错误做回退，避免掩盖其它 4xx
    if exc.status_code not in _STREAM_FALLBACK_STATUS_CODES:
        return False
    text = _status_error_text(exc)
    # 回退到默认/主配置
    return any(marker in text for marker in _STREAM_FALLBACK_ERROR_MARKERS)


def stringify_stream_delta(value: Any) -> str:
    """将流式 delta 字段归一化为字符串片段。"""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = [stringify_stream_delta(item) for item in value]
        return "".join(part for part in parts if part)
    if isinstance(value, dict):
        for key in ("text", "content", "delta", "value"):
            if value.get(key) is not None:
                return stringify_stream_delta(value.get(key))
        return ""
    return str(value)


def extract_stream_response_item(event: dict[str, Any]) -> dict[str, Any] | None:
    """从 Responses 流式事件中提取 output item。"""
    for key in ("item", "output_item", "data"):
        value = event.get(key)
        if isinstance(value, dict):
            return value
    response = event.get("response")
    if isinstance(response, dict) and isinstance(response.get("output"), list):
        return None
    if isinstance(response, dict):
        return response
    return None


def extract_stream_usage(
    event: dict[str, Any], *, api_mode: str
) -> dict[str, Any] | None:
    """从流式事件中提取 usage 统计。"""
    usage = event.get("usage")
    if not isinstance(usage, dict):
        response = event.get("response")
        if isinstance(response, dict) and isinstance(response.get("usage"), dict):
            usage = response.get("usage")
    if not isinstance(usage, dict):
        return None
    if api_mode == API_MODE_RESPONSES:
        return {
            "input_tokens": int(usage.get("input_tokens", 0) or 0),
            "output_tokens": int(usage.get("output_tokens", 0) or 0),
            "total_tokens": int(usage.get("total_tokens", 0) or 0),
        }
    return {
        "prompt_tokens": int(usage.get("prompt_tokens", 0) or 0),
        "completion_tokens": int(usage.get("completion_tokens", 0) or 0),
        "total_tokens": int(usage.get("total_tokens", 0) or 0),
    }


def ensure_tool_call_slot(
    tool_calls: list[dict[str, Any]], index: int
) -> dict[str, Any]:
    """确保 tool_calls 列表在指定 index 处存在槽位。"""
    while len(tool_calls) <= index:
        tool_calls.append(
            {
                "id": "",
                "type": "function",
                "function": {"name": "", "arguments": ""},
            }
        )
    return tool_calls[index]


def merge_tool_call_delta(
    target_tool_calls: list[dict[str, Any]], tool_delta: dict[str, Any]
) -> None:
    """将单个 tool_call delta 合并进累积结果。"""
    index = tool_delta.get("index")
    try:
        slot_index = int(index) if index is not None else len(target_tool_calls)
    except (TypeError, ValueError):
        slot_index = len(target_tool_calls)
    tool_call = ensure_tool_call_slot(target_tool_calls, slot_index)
    call_id = str(tool_delta.get("id") or "").strip()
    if call_id:
        tool_call["id"] = call_id
    tool_type = str(tool_delta.get("type") or "").strip()
    if tool_type:
        tool_call["type"] = tool_type
    function_delta = tool_delta.get("function")
    if not isinstance(function_delta, dict):
        return
    function = tool_call.setdefault("function", {"name": "", "arguments": ""})
    if not isinstance(function, dict):
        function = {"name": "", "arguments": ""}
        tool_call["function"] = function
    function_name = str(function_delta.get("name") or "").strip()
    if function_name:
        function["name"] = function_name
    arguments_delta = function_delta.get("arguments")
    if arguments_delta is not None:
        # 流式 tool arguments 按 chunk 拼接，直至 JSON 完整
        function["arguments"] = str(function.get("arguments") or "") + str(
            arguments_delta
        )


def aggregate_chat_completions_stream(
    chunks: list[dict[str, Any]],
    *,
    reasoning_replay: bool,
) -> dict[str, Any]:
    """将 Chat Completions 流式 chunk 列表聚合为完整响应 dict。"""
    content_parts: list[str] = []
    reasoning_parts: list[str] = []
    tool_calls: list[dict[str, Any]] = []
    usage: dict[str, Any] | None = None
    finish_reason = "stop"
    role = "assistant"

    for chunk_dict in chunks:
        usage = (
            extract_stream_usage(chunk_dict, api_mode=API_MODE_CHAT_COMPLETIONS)
            or usage
        )
        choices = chunk_dict.get("choices")
        if not isinstance(choices, list):
            continue
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            delta = choice.get("delta")
            if not isinstance(delta, dict):
                continue
            role_value = str(delta.get("role") or "").strip()
            if role_value:
                role = role_value
            content_delta = stringify_stream_delta(delta.get("content"))
            if content_delta:
                content_parts.append(content_delta)
            if reasoning_replay:
                reasoning_delta = stringify_thinking(delta.get("reasoning_content"))
                if reasoning_delta:
                    reasoning_parts.append(reasoning_delta)
            raw_tool_calls = delta.get("tool_calls")
            # 无 tool_calls 与有 tool_calls 走不同分支
            if isinstance(raw_tool_calls, list):
                # 逐个处理模型返回的 tool_call
                for tool_delta in raw_tool_calls:
                    if isinstance(tool_delta, dict):
                        merge_tool_call_delta(tool_calls, tool_delta)
            current_finish_reason = str(choice.get("finish_reason") or "").strip()
            if current_finish_reason:
                finish_reason = current_finish_reason

    message: dict[str, Any] = {
        "role": role,
        "content": "".join(content_parts),
    }
    if reasoning_replay:
        reasoning_text = "".join(reasoning_parts).strip()
        if reasoning_text:
            message["reasoning_content"] = reasoning_text
    # 无 tool_calls 与有 tool_calls 走不同分支
    if tool_calls:
        message["tool_calls"] = tool_calls
    result: dict[str, Any] = {
        "choices": [
            {
                "index": 0,
                "message": message,
                "finish_reason": finish_reason,
            }
        ]
    }
    if usage is not None:
        result["usage"] = usage
    return result


def aggregate_responses_stream(events: list[dict[str, Any]]) -> dict[str, Any]:
    """将 Responses 流式事件列表聚合为完整响应 dict。"""
    output_items: list[dict[str, Any]] = []
    output_text_parts: list[str] = []
    usage: dict[str, Any] | None = None
    final_response: dict[str, Any] | None = None

    for event_dict in events:
        usage = extract_stream_usage(event_dict, api_mode=API_MODE_RESPONSES) or usage
        event_type = str(event_dict.get("type") or "").strip().lower()
        response = event_dict.get("response")
        if isinstance(response, dict):
            final_response = response
        if event_type == "response.output_text.delta":
            delta = stringify_stream_delta(event_dict.get("delta"))
            if delta:
                output_text_parts.append(delta)
            continue
        if event_type == "response.completed":
            if isinstance(response, dict):
                final_response = response
            continue
        item = extract_stream_response_item(event_dict)
        if not isinstance(item, dict):
            continue
        item_type = str(item.get("type") or "").strip().lower()
        if item_type in ("message", "function_call", "reasoning"):
            output_items.append(item)

    if final_response is not None:
        if usage is not None and not isinstance(final_response.get("usage"), dict):
            final_response = dict(final_response)
            final_response["usage"] = usage
        return final_response

    # 未收到 completed 事件时，用增量 delta 合成最小可用响应
    synthesized: dict[str, Any] = {
        "output": output_items,
        "output_text": "".join(output_text_parts),
    }
    if usage is not None:
        synthesized["usage"] = usage
    return synthesized
