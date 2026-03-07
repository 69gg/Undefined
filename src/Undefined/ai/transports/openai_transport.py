from __future__ import annotations

import json
from typing import Any

API_MODE_CHAT_COMPLETIONS = "chat_completions"
API_MODE_RESPONSES = "responses"
_VALID_API_MODES = {API_MODE_CHAT_COMPLETIONS, API_MODE_RESPONSES}
_VALID_REASONING_EFFORTS = {"none", "minimal", "low", "medium", "high", "xhigh"}


def normalize_api_mode(value: Any, default: str = API_MODE_CHAT_COMPLETIONS) -> str:
    text = str(value or default).strip().lower()
    if text not in _VALID_API_MODES:
        return default
    return text


def get_api_mode(model_config: Any) -> str:
    return normalize_api_mode(
        getattr(model_config, "api_mode", API_MODE_CHAT_COMPLETIONS)
    )


def normalize_reasoning_effort(value: Any, default: str = "medium") -> str:
    text = str(value or default).strip().lower()
    if text not in _VALID_REASONING_EFFORTS:
        return default
    return text


def get_reasoning_payload(model_config: Any) -> dict[str, Any] | None:
    if not bool(getattr(model_config, "reasoning_enabled", False)):
        return None
    return {
        "effort": normalize_reasoning_effort(
            getattr(model_config, "reasoning_effort", "medium")
        )
    }


def _stringify_content(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        chunks: list[str] = []
        for item in value:
            if isinstance(item, str):
                chunks.append(item)
                continue
            if not isinstance(item, dict):
                continue
            item_type = str(item.get("type", "")).strip().lower()
            if item_type in {
                "text",
                "input_text",
                "output_text",
                "reasoning_text",
                "summary_text",
            }:
                text = item.get("text")
                if text is not None:
                    chunks.append(str(text))
                continue
            if item_type == "refusal":
                refusal = item.get("refusal")
                if refusal is not None:
                    chunks.append(str(refusal))
                continue
            if item_type == "image_url":
                image_url = item.get("image_url") or {}
                if isinstance(image_url, dict) and image_url.get("url"):
                    chunks.append(str(image_url.get("url")))
                continue
            if item_type.endswith("_url"):
                payload = item.get(item_type) or {}
                if isinstance(payload, dict) and payload.get("url"):
                    chunks.append(str(payload.get("url")))
                continue
            data = item.get("data")
            if isinstance(data, dict) and data.get("text") is not None:
                chunks.append(str(data.get("text")))
        return "\n".join(chunk for chunk in chunks if chunk)
    if isinstance(value, dict):
        if value.get("text") is not None:
            return str(value.get("text"))
        if value.get("content") is not None:
            return _stringify_content(value.get("content"))
        return json.dumps(value, ensure_ascii=False, default=str)
    return str(value)


def _content_to_response_parts(content: Any) -> list[dict[str, Any]]:
    if isinstance(content, str):
        return [{"type": "input_text", "text": content}]
    if not isinstance(content, list):
        text = _stringify_content(content)
        return [{"type": "input_text", "text": text}] if text else []

    parts: list[dict[str, Any]] = []
    for item in content:
        if isinstance(item, str):
            if item:
                parts.append({"type": "input_text", "text": item})
            continue
        if not isinstance(item, dict):
            continue
        item_type = str(item.get("type", "")).strip().lower()
        if item_type in {"text", "input_text"}:
            text_value: Any | None = item.get("text")
            if text_value is None:
                data = item.get("data")
                if isinstance(data, dict):
                    text_value = data.get("text")
            if text_value is not None:
                parts.append({"type": "input_text", "text": str(text_value)})
            continue
        if item_type == "image_url":
            image = item.get("image_url") or {}
            if isinstance(image, dict) and image.get("url"):
                parts.append(
                    {
                        "type": "input_image",
                        "image_url": str(image.get("url")),
                        "detail": str(image.get("detail") or "auto"),
                    }
                )
            continue
        if item_type.endswith("_url"):
            image = item.get(item_type) or {}
            if isinstance(image, dict) and image.get("url"):
                parts.append(
                    {
                        "type": "input_image",
                        "image_url": str(image.get("url")),
                        "detail": str(image.get("detail") or "auto"),
                    }
                )
            continue
        if item_type == "input_image":
            image_url = item.get("image_url")
            if image_url:
                parts.append(
                    {
                        "type": "input_image",
                        "image_url": str(image_url),
                        "detail": str(item.get("detail") or "auto"),
                    }
                )
            continue
        text = _stringify_content(item)
        if text:
            parts.append({"type": "input_text", "text": text})
    return parts


def _message_to_responses_input(
    message: dict[str, Any],
    internal_to_api: dict[str, str],
) -> list[dict[str, Any]]:
    role = str(message.get("role", "")).strip().lower()
    if not role:
        return []

    if role == "tool":
        tool_call_id = str(message.get("tool_call_id", "")).strip()
        if not tool_call_id:
            return []
        return [
            {
                "type": "function_call_output",
                "call_id": tool_call_id,
                "output": _stringify_content(message.get("content")),
            }
        ]

    items: list[dict[str, Any]] = []
    content_parts = _content_to_response_parts(message.get("content"))
    if role in {"user", "assistant", "system", "developer"} and content_parts:
        items.append(
            {
                "type": "message",
                "role": role,
                "content": content_parts,
            }
        )

    if role == "assistant":
        tool_calls = message.get("tool_calls")
        if isinstance(tool_calls, list):
            for tool_call in tool_calls:
                if not isinstance(tool_call, dict):
                    continue
                function = tool_call.get("function") or {}
                if not isinstance(function, dict):
                    continue
                name = str(function.get("name", "")).strip()
                if not name:
                    continue
                api_name = internal_to_api.get(name, name)
                call_id = str(
                    tool_call.get("id") or tool_call.get("call_id") or ""
                ).strip()
                if not call_id:
                    continue
                items.append(
                    {
                        "type": "function_call",
                        "call_id": call_id,
                        "name": api_name,
                        "arguments": str(function.get("arguments", "{}")),
                    }
                )
    return items


def _messages_to_instruction_text(messages: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for message in messages:
        role = str(message.get("role", "")).strip().lower()
        if role not in {"system", "developer"}:
            continue
        text = _stringify_content(message.get("content"))
        if text:
            lines.append(text)
    return "\n\n".join(line for line in lines if line).strip()


def _messages_to_responses_input(
    messages: list[dict[str, Any]],
    internal_to_api: dict[str, str],
    *,
    include_system: bool,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for message in messages:
        role = str(message.get("role", "")).strip().lower()
        if not include_system and role in {"system", "developer"}:
            continue
        if (
            not include_system
            and role == "assistant"
            and not message.get("content")
            and not message.get("tool_calls")
        ):
            continue
        items.extend(_message_to_responses_input(message, internal_to_api))
    return items


def _normalize_responses_tool_choice(tool_choice: Any) -> Any:
    if not isinstance(tool_choice, dict):
        return tool_choice
    choice_type = str(tool_choice.get("type", "")).strip().lower()
    if choice_type == "function":
        function = tool_choice.get("function")
        if isinstance(function, dict):
            name = str(function.get("name", "")).strip()
            if name:
                return {"type": "function", "name": name}
    return tool_choice


def build_responses_request_body(
    model_config: Any,
    messages: list[dict[str, Any]],
    max_tokens: int,
    *,
    tools: list[dict[str, Any]] | None,
    tool_choice: Any,
    extra_kwargs: dict[str, Any],
    internal_to_api: dict[str, str],
    transport_state: dict[str, Any] | None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": getattr(model_config, "model_name"),
        "max_output_tokens": max_tokens,
    }
    reasoning = get_reasoning_payload(model_config)
    if reasoning is not None:
        body["reasoning"] = reasoning
    if tools:
        body["tools"] = tools
        body["tool_choice"] = _normalize_responses_tool_choice(tool_choice)

    previous_response_id = ""
    start_index = 0
    if isinstance(transport_state, dict):
        previous_response_id = str(
            transport_state.get("previous_response_id") or ""
        ).strip()
        try:
            start_index = int(transport_state.get("tool_result_start_index") or 0)
        except Exception:
            start_index = 0
        if start_index < 0:
            start_index = 0

    if previous_response_id:
        body["previous_response_id"] = previous_response_id
        body["input"] = _messages_to_responses_input(
            messages[start_index:], internal_to_api, include_system=True
        )
    else:
        instructions = _messages_to_instruction_text(messages)
        if instructions:
            body["instructions"] = instructions
        body["input"] = _messages_to_responses_input(
            messages, internal_to_api, include_system=False
        )

    body.update(extra_kwargs)
    return body


def _collect_reasoning_text(output: list[dict[str, Any]]) -> str:
    chunks: list[str] = []
    for item in output:
        if not isinstance(item, dict) or item.get("type") != "reasoning":
            continue
        content = item.get("content")
        if isinstance(content, list):
            for part in content:
                if not isinstance(part, dict):
                    continue
                if part.get("type") == "reasoning_text" and part.get("text"):
                    chunks.append(str(part.get("text")))
        summary = item.get("summary")
        if isinstance(summary, list):
            for part in summary:
                if not isinstance(part, dict):
                    continue
                if part.get("type") == "summary_text" and part.get("text"):
                    chunks.append(str(part.get("text")))
    return "\n".join(chunk for chunk in chunks if chunk).strip()


def normalize_responses_result(
    result: dict[str, Any],
    api_to_internal: dict[str, str] | None = None,
) -> dict[str, Any]:
    normalized = dict(result)
    output_raw = result.get("output")
    output = output_raw if isinstance(output_raw, list) else []

    assistant_texts: list[str] = []
    tool_calls: list[dict[str, Any]] = []
    for item in output:
        if not isinstance(item, dict):
            continue
        item_type = str(item.get("type", "")).strip().lower()
        if (
            item_type == "message"
            and str(item.get("role", "")).strip().lower() == "assistant"
        ):
            content = item.get("content")
            if isinstance(content, list):
                for part in content:
                    if not isinstance(part, dict):
                        continue
                    part_type = str(part.get("type", "")).strip().lower()
                    if part_type == "output_text" and part.get("text") is not None:
                        assistant_texts.append(str(part.get("text")))
                    elif part_type == "refusal" and part.get("refusal") is not None:
                        assistant_texts.append(str(part.get("refusal")))
        elif item_type == "function_call":
            function_name = str(item.get("name", "")).strip()
            if api_to_internal:
                function_name = api_to_internal.get(function_name, function_name)
            call_id = str(item.get("call_id") or item.get("id") or "").strip()
            if not function_name or not call_id:
                continue
            tool_calls.append(
                {
                    "id": call_id,
                    "type": "function",
                    "function": {
                        "name": function_name,
                        "arguments": str(item.get("arguments", "{}")),
                    },
                }
            )

    message: dict[str, Any] = {
        "role": "assistant",
        "content": "\n".join(text for text in assistant_texts if text).strip(),
    }
    reasoning_content = _collect_reasoning_text(output)
    if reasoning_content:
        message["reasoning_content"] = reasoning_content
    if tool_calls:
        message["tool_calls"] = tool_calls

    normalized["choices"] = [
        {
            "index": 0,
            "message": message,
            "finish_reason": "tool_calls" if tool_calls else "stop",
        }
    ]

    usage = result.get("usage")
    if isinstance(usage, dict):
        normalized["usage"] = {
            "prompt_tokens": int(usage.get("input_tokens", 0) or 0),
            "completion_tokens": int(usage.get("output_tokens", 0) or 0),
            "total_tokens": int(usage.get("total_tokens", 0) or 0),
        }

    return normalized
