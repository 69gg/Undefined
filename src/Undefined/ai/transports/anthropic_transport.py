"""Anthropic Messages request/response conversion helpers."""

from __future__ import annotations

import json
import logging
import re
from copy import deepcopy
from typing import Any

from Undefined.ai.transports.openai_transport import normalize_reasoning_effort

logger = logging.getLogger(__name__)

ANTHROPIC_CONTENT_BLOCKS_KEY = "_anthropic_content_blocks"

_ANTHROPIC_KNOWN_FIELDS: frozenset[str] = frozenset(
    {
        "cache_control",
        "container",
        "inference_geo",
        "max_tokens",
        "messages",
        "metadata",
        "model",
        "output_config",
        "service_tier",
        "stop_sequences",
        "stream",
        "system",
        "temperature",
        "thinking",
        "tool_choice",
        "tools",
        "top_k",
        "top_p",
        "user_profile_id",
        "extra_headers",
        "extra_query",
        "extra_body",
        "timeout",
    }
)

_DATA_URL_RE = re.compile(
    r"^data:(?P<media_type>[^;,]+);base64,(?P<data>.*)$",
    re.IGNORECASE | re.DOTALL,
)


def split_anthropic_params(
    body: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Split SDK-known Messages parameters from provider extensions."""
    known: dict[str, Any] = {}
    extra: dict[str, Any] = {}
    for key, value in body.items():
        if key in _ANTHROPIC_KNOWN_FIELDS:
            known[key] = value
        else:
            extra[key] = value
    return known, extra


def _stringify_content(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        chunks = [_stringify_content(item) for item in value]
        return "\n".join(chunk for chunk in chunks if chunk)
    if isinstance(value, dict):
        for key in ("text", "content", "output"):
            if value.get(key) is not None:
                return _stringify_content(value[key])
        return json.dumps(value, ensure_ascii=False, default=str)
    return str(value)


def _image_source(url: str) -> dict[str, Any]:
    match = _DATA_URL_RE.match(url)
    if match:
        return {
            "type": "base64",
            "media_type": match.group("media_type"),
            "data": match.group("data"),
        }
    return {"type": "url", "url": url}


def _content_to_anthropic_blocks(content: Any) -> list[dict[str, Any]]:
    if isinstance(content, str):
        return [{"type": "text", "text": content}] if content else []
    if not isinstance(content, list):
        text = _stringify_content(content)
        return [{"type": "text", "text": text}] if text else []

    blocks: list[dict[str, Any]] = []
    for item in content:
        if isinstance(item, str):
            if item:
                blocks.append({"type": "text", "text": item})
            continue
        if not isinstance(item, dict):
            continue
        item_type = str(item.get("type") or "").strip().lower()
        if item_type in {"text", "input_text", "output_text"}:
            text_value = item.get("text")
            if text_value is not None:
                blocks.append({"type": "text", "text": str(text_value)})
            continue
        if item_type in {"image", "document"} and isinstance(item.get("source"), dict):
            blocks.append(deepcopy(item))
            continue
        if item_type in {"image_url", "input_image"}:
            raw_image = item.get("image_url")
            if isinstance(raw_image, dict):
                raw_image = raw_image.get("url")
            url = str(raw_image or "").strip()
            if url:
                blocks.append({"type": "image", "source": _image_source(url)})
            continue
        if item_type.endswith("_url"):
            raise ValueError(
                f"Anthropic Messages 不支持内容类型 {item_type!r}；"
                "请改用 text、image 或 document block"
            )
        text = _stringify_content(item)
        if text:
            blocks.append({"type": "text", "text": text})
    return blocks


def _append_anthropic_message(
    messages: list[dict[str, Any]],
    *,
    role: str,
    blocks: list[dict[str, Any]],
) -> None:
    if not blocks:
        return
    if messages and messages[-1].get("role") == role:
        existing = messages[-1].get("content")
        if isinstance(existing, list):
            existing.extend(blocks)
            return
    messages.append({"role": role, "content": blocks})


def _system_text(messages: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for message in messages:
        role = str(message.get("role") or "").strip().lower()
        if role not in {"system", "developer"}:
            continue
        text = _stringify_content(message.get("content")).strip()
        if text:
            parts.append(text)
    return "\n\n".join(parts)


def _messages_to_anthropic(
    messages: list[dict[str, Any]],
    *,
    preserve_reasoning: bool,
) -> list[dict[str, Any]]:
    converted: list[dict[str, Any]] = []
    for message in messages:
        role = str(message.get("role") or "").strip().lower()
        if role in {"system", "developer"}:
            continue
        if role == "tool":
            tool_use_id = str(message.get("tool_call_id") or "").strip()
            if not tool_use_id:
                continue
            block: dict[str, Any] = {
                "type": "tool_result",
                "tool_use_id": tool_use_id,
                "content": _stringify_content(message.get("content")),
            }
            if message.get("is_error") is not None:
                block["is_error"] = bool(message.get("is_error"))
            _append_anthropic_message(converted, role="user", blocks=[block])
            continue
        if role not in {"user", "assistant"}:
            continue

        if role == "assistant" and isinstance(
            message.get(ANTHROPIC_CONTENT_BLOCKS_KEY), list
        ):
            raw_blocks = deepcopy(message[ANTHROPIC_CONTENT_BLOCKS_KEY])
            if not preserve_reasoning:
                raw_blocks = [
                    block
                    for block in raw_blocks
                    if not isinstance(block, dict)
                    or str(block.get("type") or "").strip().lower()
                    not in {"thinking", "redacted_thinking"}
                ]
            _append_anthropic_message(
                converted,
                role="assistant",
                blocks=[block for block in raw_blocks if isinstance(block, dict)],
            )
            continue

        blocks = _content_to_anthropic_blocks(message.get("content"))
        if role == "assistant":
            tool_calls = message.get("tool_calls")
            if isinstance(tool_calls, list):
                for tool_call in tool_calls:
                    if not isinstance(tool_call, dict):
                        continue
                    function = tool_call.get("function")
                    if not isinstance(function, dict):
                        continue
                    name = str(function.get("name") or "").strip()
                    call_id = str(
                        tool_call.get("id") or tool_call.get("call_id") or ""
                    ).strip()
                    if not name or not call_id:
                        continue
                    raw_arguments = function.get("arguments", "{}")
                    try:
                        tool_input = (
                            json.loads(raw_arguments)
                            if isinstance(raw_arguments, str)
                            else raw_arguments
                        )
                    except (TypeError, ValueError, json.JSONDecodeError):
                        tool_input = {}
                    if not isinstance(tool_input, dict):
                        tool_input = {}
                    blocks.append(
                        {
                            "type": "tool_use",
                            "id": call_id,
                            "name": name,
                            "input": tool_input,
                        }
                    )
        _append_anthropic_message(converted, role=role, blocks=blocks)
    return converted


def _normalize_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for tool in tools:
        if not isinstance(tool, dict) or tool.get("type") != "function":
            continue
        function = tool.get("function")
        if not isinstance(function, dict):
            continue
        name = str(function.get("name") or "").strip()
        if not name:
            continue
        parameters = function.get("parameters")
        if not isinstance(parameters, dict):
            parameters = {"type": "object", "properties": {}}
        item: dict[str, Any] = {"name": name, "input_schema": parameters}
        if function.get("description") is not None:
            item["description"] = str(function["description"])
        if function.get("strict") is not None:
            item["strict"] = bool(function["strict"])
        normalized.append(item)
    return normalized


def _normalize_tool_choice(
    tool_choice: Any,
    internal_to_api: dict[str, str] | None = None,
) -> dict[str, Any] | None:
    if isinstance(tool_choice, str):
        value = tool_choice.strip().lower()
        if value == "required":
            return {"type": "any"}
        if value in {"auto", "none"}:
            return {"type": value}
        return None
    if not isinstance(tool_choice, dict):
        return None
    choice_type = str(tool_choice.get("type") or "").strip().lower()
    if choice_type in {"auto", "any", "none"}:
        return deepcopy(tool_choice)
    if choice_type in {"function", "tool"}:
        function = tool_choice.get("function")
        name = (
            function.get("name")
            if isinstance(function, dict)
            else tool_choice.get("name")
        )
        name_text = str(name or "").strip()
        if name_text:
            if internal_to_api:
                name_text = internal_to_api.get(name_text, name_text)
            return {"type": "tool", "name": name_text}
    return None


def _thinking_payload(model_config: Any, max_tokens: int) -> dict[str, Any] | None:
    if not bool(getattr(model_config, "thinking_param_enabled", True)) or not bool(
        getattr(model_config, "thinking_enabled", False)
    ):
        return None
    if not bool(getattr(model_config, "thinking_include_budget", True)):
        return {"type": "adaptive"}
    budget = int(getattr(model_config, "thinking_budget_tokens", 0))
    if budget < 1024:
        raise ValueError(
            "Anthropic 手动 thinking 要求 thinking_budget_tokens >= 1024，"
            f"当前为 {budget}；如需 adaptive thinking，请设置 "
            "thinking_include_budget=false"
        )
    if max_tokens > 0 and budget >= max_tokens:
        raise ValueError(
            "Anthropic 手动 thinking 要求 thinking_budget_tokens "
            f"小于本次 max_tokens ({max_tokens})，当前为 {budget}；"
            "如需 adaptive thinking，请设置 thinking_include_budget=false"
        )
    return {"type": "enabled", "budget_tokens": budget}


def _validate_thinking_override(value: Any, max_tokens: int) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("Anthropic thinking 覆盖值必须是对象")
    thinking = deepcopy(value)
    thinking_type = str(thinking.get("type") or "").strip().lower()
    if thinking_type == "disabled":
        return {"type": "disabled"}
    if thinking_type == "adaptive":
        thinking.pop("budget_tokens", None)
        thinking["type"] = "adaptive"
        return thinking
    if thinking_type != "enabled":
        raise ValueError("Anthropic thinking.type 必须是 enabled/adaptive/disabled")
    raw_budget = thinking.get("budget_tokens")
    try:
        budget = int(raw_budget) if raw_budget is not None else 0
    except (TypeError, ValueError) as exc:
        raise ValueError("Anthropic enabled thinking 必须提供 budget_tokens") from exc
    if budget < 1024:
        raise ValueError(
            f"Anthropic 手动 thinking 要求 budget_tokens >= 1024，当前为 {budget}"
        )
    if max_tokens > 0 and budget >= max_tokens:
        raise ValueError(
            "Anthropic 手动 thinking 要求 budget_tokens "
            f"小于本次 max_tokens ({max_tokens})，当前为 {budget}"
        )
    thinking["type"] = "enabled"
    thinking["budget_tokens"] = budget
    return thinking


def build_anthropic_messages_request_body(
    model_config: Any,
    messages: list[dict[str, Any]],
    max_tokens: int,
    *,
    tools: list[dict[str, Any]] | None,
    tool_choice: Any,
    extra_kwargs: dict[str, Any],
    internal_to_api: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build a canonical Anthropic Messages request body."""
    if max_tokens <= 0:
        raise ValueError(
            f"Anthropic Messages 要求 max_tokens 为正整数，当前为 {max_tokens}"
        )
    body: dict[str, Any] = {
        "model": getattr(model_config, "model_name"),
        "max_tokens": max_tokens,
    }
    preserve_reasoning = bool(getattr(model_config, "reasoning_content_replay", True))
    body["messages"] = _messages_to_anthropic(
        messages,
        preserve_reasoning=preserve_reasoning,
    )
    system = _system_text(messages)
    if system:
        body["system"] = system

    override_marker = object()
    thinking_override = extra_kwargs.pop("thinking", override_marker)
    if thinking_override is override_marker:
        thinking = _thinking_payload(model_config, max_tokens)
    else:
        thinking = _validate_thinking_override(thinking_override, max_tokens)
    if thinking is not None:
        body["thinking"] = thinking

    output_config_value = extra_kwargs.pop("output_config", None)
    if output_config_value is not None and not isinstance(output_config_value, dict):
        raise ValueError("Anthropic output_config 请求参数必须是对象")
    output_config = (
        deepcopy(output_config_value) if isinstance(output_config_value, dict) else {}
    )
    if bool(getattr(model_config, "reasoning_enabled", False)):
        output_config["effort"] = normalize_reasoning_effort(
            getattr(model_config, "reasoning_effort", "medium")
        )
    if output_config:
        body["output_config"] = output_config

    extra_kwargs.pop("reasoning", None)
    extra_kwargs.pop("reasoning_effort", None)
    extra_kwargs.pop("prompt_cache_key", None)

    if tools:
        normalized_tools = _normalize_tools(tools)
        if normalized_tools:
            body["tools"] = normalized_tools
            normalized_choice = _normalize_tool_choice(tool_choice, internal_to_api)
            if normalized_choice is not None:
                thinking_active = isinstance(thinking, dict) and thinking.get(
                    "type"
                ) in {"enabled", "adaptive"}
                if thinking_active and normalized_choice.get("type") in {
                    "any",
                    "tool",
                }:
                    logger.warning(
                        "[anthropic.compat] thinking 启用时不支持强制 tool_choice，已降级为 auto"
                    )
                    normalized_choice = {"type": "auto"}
                body["tool_choice"] = normalized_choice

    body.update(extra_kwargs)
    return body


def normalize_anthropic_result(
    result: dict[str, Any],
    api_to_internal: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Normalize an Anthropic Message into the internal Chat response shape."""
    normalized = dict(result)
    raw_content = result.get("content")
    content_blocks = raw_content if isinstance(raw_content, list) else []
    text_parts: list[str] = []
    reasoning_parts: list[str] = []
    tool_calls: list[dict[str, Any]] = []
    for block in content_blocks:
        if not isinstance(block, dict):
            continue
        block_type = str(block.get("type") or "").strip().lower()
        if block_type == "text" and block.get("text") is not None:
            text_parts.append(str(block["text"]))
        elif block_type == "thinking" and block.get("thinking") is not None:
            reasoning_parts.append(str(block["thinking"]))
        elif block_type == "tool_use":
            name = str(block.get("name") or "").strip()
            call_id = str(block.get("id") or "").strip()
            if api_to_internal:
                name = api_to_internal.get(name, name)
            if not name or not call_id:
                continue
            tool_calls.append(
                {
                    "id": call_id,
                    "type": "function",
                    "function": {
                        "name": name,
                        "arguments": json.dumps(
                            block.get("input", {}),
                            ensure_ascii=False,
                            separators=(",", ":"),
                            default=str,
                        ),
                    },
                }
            )

    message: dict[str, Any] = {
        "role": "assistant",
        "content": "".join(text_parts),
    }
    if content_blocks:
        message[ANTHROPIC_CONTENT_BLOCKS_KEY] = deepcopy(content_blocks)
    reasoning_content = "\n".join(part for part in reasoning_parts if part).strip()
    if reasoning_content:
        message["reasoning_content"] = reasoning_content
    if tool_calls:
        message["tool_calls"] = tool_calls

    stop_reason = str(result.get("stop_reason") or "").strip().lower()
    finish_reason = {
        "tool_use": "tool_calls",
        "max_tokens": "length",
        "refusal": "content_filter",
    }.get(stop_reason, "stop")
    normalized["choices"] = [
        {"index": 0, "message": message, "finish_reason": finish_reason}
    ]

    usage = result.get("usage")
    if isinstance(usage, dict):
        prompt_tokens = sum(
            int(usage.get(key, 0) or 0)
            for key in (
                "input_tokens",
                "cache_creation_input_tokens",
                "cache_read_input_tokens",
            )
        )
        completion_tokens = int(usage.get("output_tokens", 0) or 0)
        normalized["_anthropic_usage"] = deepcopy(usage)
        normalized["usage"] = {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        }
    return normalized


__all__ = [
    "ANTHROPIC_CONTENT_BLOCKS_KEY",
    "build_anthropic_messages_request_body",
    "normalize_anthropic_result",
    "split_anthropic_params",
]
