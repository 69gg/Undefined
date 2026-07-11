from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

from Undefined.config.api_modes import (
    API_MODE_OPENAI_CHAT_COMPLETIONS,
    API_MODE_OPENAI_RESPONSES,
    normalize_api_mode,
)

API_MODE_CHAT_COMPLETIONS = API_MODE_OPENAI_CHAT_COMPLETIONS
API_MODE_RESPONSES = API_MODE_OPENAI_RESPONSES
RESPONSES_OUTPUT_ITEMS_KEY = "_responses_output_items"
CHAT_REASONING_REPLAY_KEY = "_chat_reasoning_replay"
RESPONSES_REASONING_REPLAY_KEY = "_responses_reasoning_replay"
_RESPONSES_REPLAY_STRIP_KEYS = {"status"}
_RESPONSES_REASONING_ITEM_TYPES = {"reasoning", "compaction"}

CHAT_REASONING_WIRE_FIELDS: tuple[str, ...] = (
    "reasoning_content",
    "reasoning_details",
    "reasoning",
    "encrypted_content",
    "thinking",
)
_RESPONSES_COMPAT_REASONING_FIELDS: frozenset[str] = frozenset(
    field for field in CHAT_REASONING_WIRE_FIELDS if field != "reasoning"
)


def get_api_mode(model_config: Any) -> str:
    return normalize_api_mode(
        getattr(model_config, "api_mode", API_MODE_CHAT_COMPLETIONS)
    )


def normalize_reasoning_effort(value: Any, default: str = "medium") -> str:
    return str(value if value is not None else default).strip() or default


def get_reasoning_payload(model_config: Any) -> dict[str, Any] | None:
    return get_effort_payload(model_config)


def get_thinking_payload(model_config: Any) -> dict[str, Any] | None:
    """构建 thinking 请求参数，仅由 thinking_* 配置控制。"""
    if not bool(getattr(model_config, "thinking_enabled", False)):
        return None
    param: dict[str, Any] = {"type": "enabled"}
    if bool(getattr(model_config, "thinking_include_budget", True)):
        param["budget_tokens"] = int(getattr(model_config, "thinking_budget_tokens", 0))
    return param


def get_effort_payload(model_config: Any) -> dict[str, Any] | None:
    """构建 effort 请求参数（仅在 reasoning_enabled 启用时生效）。"""
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


def _reasoning_detail_text(value: Any) -> str:
    if not isinstance(value, list):
        return ""
    chunks: list[str] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        item_type = str(item.get("type") or "").strip().lower()
        if item_type in {"reasoning.text", "reasoning_text"}:
            text = item.get("text")
            if text is not None:
                chunks.append(str(text))
        elif item_type in {"reasoning.summary", "summary_text"}:
            summary = item.get("summary")
            if summary is None:
                summary = item.get("text")
            if summary is not None:
                chunks.append(str(summary))
    return "\n".join(chunk for chunk in chunks if chunk).strip()


def _structured_reasoning_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        detail_text = _reasoning_detail_text(value)
        if detail_text:
            return detail_text
        chunks = [_structured_reasoning_text(item) for item in value]
        return "\n".join(chunk for chunk in chunks if chunk).strip()
    if not isinstance(value, dict):
        return ""
    for key in ("text", "summary", "content", "reasoning_content", "thinking"):
        if key not in value:
            continue
        text = _structured_reasoning_text(value.get(key))
        if text:
            return text
    return ""


def extract_chat_reasoning_text(message: dict[str, Any]) -> str:
    """Extract readable reasoning without exposing opaque encrypted payloads."""
    direct = message.get("reasoning_content")
    if direct is not None:
        text = _structured_reasoning_text(direct)
        if text:
            return text
    details = _reasoning_detail_text(message.get("reasoning_details"))
    if details:
        return details
    for key in ("reasoning", "thinking"):
        text = _structured_reasoning_text(message.get(key))
        if text:
            return text
    return ""


def copy_chat_reasoning_wire_fields(message: dict[str, Any]) -> dict[str, Any]:
    """Copy only known reasoning fields that compatible Chat APIs round-trip."""
    return {
        key: deepcopy(message[key])
        for key in CHAT_REASONING_WIRE_FIELDS
        if key in message and message[key] is not None
    }


def normalize_chat_completions_result(result: dict[str, Any]) -> dict[str, Any]:
    """Attach readable and lossless reasoning metadata to Chat responses."""
    choices = result.get("choices")
    if not isinstance(choices, list):
        return result

    normalized = dict(result)
    normalized_choices: list[Any] = []
    changed = False
    for choice in choices:
        if not isinstance(choice, dict):
            normalized_choices.append(choice)
            continue
        message = choice.get("message")
        if not isinstance(message, dict):
            normalized_choices.append(choice)
            continue
        wire_fields = copy_chat_reasoning_wire_fields(message)
        readable = extract_chat_reasoning_text(message)
        if not wire_fields and not readable:
            normalized_choices.append(choice)
            continue
        normalized_message = dict(message)
        if wire_fields:
            normalized_message[CHAT_REASONING_REPLAY_KEY] = wire_fields
        if readable and normalized_message.get("reasoning_content") is None:
            normalized_message["reasoning_content"] = readable
        normalized_choice = dict(choice)
        normalized_choice["message"] = normalized_message
        normalized_choices.append(normalized_choice)
        changed = True
    if changed:
        normalized["choices"] = normalized_choices
    return normalized


def _response_text_part_type(role: str) -> str:
    return "output_text" if role == "assistant" else "input_text"


def _content_to_response_parts(
    content: Any,
    *,
    role: str,
) -> list[dict[str, Any]]:
    text_part_type = _response_text_part_type(role)
    if isinstance(content, str):
        return [{"type": text_part_type, "text": content}] if content else []
    if not isinstance(content, list):
        text = _stringify_content(content)
        return [{"type": text_part_type, "text": text}] if text else []

    parts: list[dict[str, Any]] = []
    for item in content:
        if isinstance(item, str):
            if item:
                parts.append({"type": text_part_type, "text": item})
            continue
        if not isinstance(item, dict):
            continue
        item_type = str(item.get("type", "")).strip().lower()
        if item_type in {"text", "input_text", "output_text"}:
            text_value: Any | None = item.get("text")
            if text_value is None:
                data = item.get("data")
                if isinstance(data, dict):
                    text_value = data.get("text")
            if text_value is not None:
                parts.append({"type": text_part_type, "text": str(text_value)})
            continue
        if item_type == "refusal":
            refusal_value = item.get("refusal")
            if refusal_value is None:
                continue
            if role == "assistant":
                parts.append({"type": "refusal", "refusal": str(refusal_value)})
            else:
                parts.append({"type": text_part_type, "text": str(refusal_value)})
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
            parts.append({"type": text_part_type, "text": text})
    return parts


def _responses_compat_reasoning_fields(
    message: dict[str, Any],
    *,
    allow_readable_fallback: bool,
) -> dict[str, Any]:
    raw_reasoning = message.get(RESPONSES_REASONING_REPLAY_KEY)
    if isinstance(raw_reasoning, dict):
        replay_fields = {
            str(key): deepcopy(value)
            for key, value in raw_reasoning.items()
            if str(key) in _RESPONSES_COMPAT_REASONING_FIELDS and value is not None
        }
        if replay_fields:
            return replay_fields
    if allow_readable_fallback and message.get("reasoning_content") is not None:
        return {"reasoning_content": deepcopy(message["reasoning_content"])}
    return {}


def _message_to_responses_input(
    message: dict[str, Any],
    internal_to_api: dict[str, str],
    *,
    preserve_reasoning: bool,
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

    if role == "assistant":
        output_items = message.get(RESPONSES_OUTPUT_ITEMS_KEY)
        if isinstance(output_items, list):
            replay_items = _copy_responses_output_items(
                output_items,
                internal_to_api,
                preserve_reasoning=preserve_reasoning,
            )
            if replay_items:
                if preserve_reasoning:
                    has_original_reasoning = any(
                        str(item.get("type") or "").strip().lower()
                        in _RESPONSES_REASONING_ITEM_TYPES
                        or any(
                            field in item and item[field] is not None
                            for field in _RESPONSES_COMPAT_REASONING_FIELDS
                        )
                        for item in replay_items
                    )
                    compat_reasoning = _responses_compat_reasoning_fields(
                        message,
                        allow_readable_fallback=not has_original_reasoning,
                    )
                    if compat_reasoning:
                        assistant_item = next(
                            (
                                item
                                for item in replay_items
                                if str(item.get("type") or "").strip().lower()
                                == "message"
                                and str(item.get("role") or "").strip().lower()
                                == "assistant"
                            ),
                            None,
                        )
                        if assistant_item is None:
                            assistant_item = {
                                "type": "message",
                                "role": "assistant",
                                "content": _content_to_response_parts(
                                    message.get("content"), role="assistant"
                                ),
                            }
                            replay_items.insert(0, assistant_item)
                        for key, value in compat_reasoning.items():
                            assistant_item[str(key)] = deepcopy(value)
                return replay_items

    items: list[dict[str, Any]] = []
    content_parts = _content_to_response_parts(message.get("content"), role=role)
    compat_reasoning = (
        _responses_compat_reasoning_fields(
            message,
            allow_readable_fallback=True,
        )
        if role == "assistant" and preserve_reasoning
        else {}
    )
    if role in {"user", "assistant", "system", "developer"} and (
        content_parts or compat_reasoning
    ):
        item: dict[str, Any] = {
            "type": "message",
            "role": role,
            "content": content_parts,
        }
        if role == "assistant":
            phase = message.get("phase")
            if phase is not None:
                item["phase"] = str(phase)
            for key, value in compat_reasoning.items():
                item[key] = value
        items.append(item)

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
    preserve_reasoning: bool,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for message in messages:
        role = str(message.get("role", "")).strip().lower()
        if not include_system and role in {"system", "developer"}:
            continue
        items.extend(
            _message_to_responses_input(
                message,
                internal_to_api,
                preserve_reasoning=preserve_reasoning,
            )
        )
    return items


def _normalize_responses_tools(
    tools: list[dict[str, Any]],
    internal_to_api: dict[str, str],
) -> list[dict[str, Any]]:
    normalized_tools: list[dict[str, Any]] = []
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        tool_type = str(tool.get("type", "")).strip().lower()
        if tool_type != "function":
            normalized_tools.append(dict(tool))
            continue

        function = tool.get("function")
        if not isinstance(function, dict):
            normalized_tools.append(dict(tool))
            continue

        name = str(function.get("name", "")).strip()
        if not name:
            normalized_tools.append(dict(tool))
            continue

        api_name = internal_to_api.get(name, name)
        normalized_tool: dict[str, Any] = {
            "type": "function",
            "name": api_name,
        }
        description = function.get("description")
        if description is not None:
            normalized_tool["description"] = description
        parameters = function.get("parameters")
        if parameters is not None:
            normalized_tool["parameters"] = parameters
        strict = function.get("strict")
        if strict is not None:
            normalized_tool["strict"] = strict
        normalized_tools.append(normalized_tool)
    return normalized_tools


def _normalize_responses_tool_choice(
    tool_choice: Any,
    internal_to_api: dict[str, str],
    *,
    compat_mode: bool = False,
) -> tuple[Any, str | None]:
    if not isinstance(tool_choice, dict):
        return tool_choice, None
    choice_type = str(tool_choice.get("type", "")).strip().lower()
    if choice_type != "function":
        return tool_choice, None

    name = ""
    function = tool_choice.get("function")
    if isinstance(function, dict):
        name = str(function.get("name", "")).strip()
    elif tool_choice.get("name") is not None:
        name = str(tool_choice.get("name", "")).strip()

    if not name:
        return "auto", None

    api_name = internal_to_api.get(name, name)
    if compat_mode:
        return "required", api_name
    return {"type": "function", "name": api_name}, None


def _copy_responses_output_items(
    items: list[Any],
    name_mapping: dict[str, str] | None = None,
    *,
    preserve_reasoning: bool = True,
) -> list[dict[str, Any]]:
    copied: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        cloned = deepcopy(item)
        item_type = str(cloned.get("type", "")).strip().lower()
        if not preserve_reasoning and item_type in _RESPONSES_REASONING_ITEM_TYPES:
            continue
        if not preserve_reasoning:
            for key in CHAT_REASONING_WIRE_FIELDS:
                cloned.pop(key, None)
            content = cloned.get("content")
            if isinstance(content, list):
                cloned["content"] = [
                    part
                    for part in content
                    if not isinstance(part, dict)
                    or (
                        str(part.get("type") or "").strip().lower()
                        not in {
                            "reasoning_text",
                            "summary_text",
                            "thinking",
                            "redacted_thinking",
                        }
                        and not str(part.get("type") or "")
                        .strip()
                        .lower()
                        .startswith("reasoning.")
                    )
                ]
        if item_type == "function_call" and name_mapping:
            name = str(cloned.get("name", "")).strip()
            if name:
                cloned["name"] = name_mapping.get(name, name)
        if item_type == "function_call":
            if cloned.get("namespace") is None:
                cloned.pop("namespace", None)
            if cloned.get("id") is None:
                cloned.pop("id", None)
            item_id = str(cloned.get("id") or "").strip()
            call_id = str(cloned.get("call_id") or "").strip()
            # Some compatibility gateways incorrectly mirror the model's call_id into
            # function_call.id. OpenAI accepts id as optional, but when present it must
            if item_id and not item_id.startswith("fc"):
                if not call_id and item_id.startswith("call"):
                    cloned["call_id"] = item_id
                cloned.pop("id", None)
        for key in _RESPONSES_REPLAY_STRIP_KEYS:
            cloned.pop(key, None)
        copied.append(cloned)
    return copied


def _normalize_include_values(value: Any) -> list[str]:
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, list):
        return [text for item in value if (text := str(item or "").strip())]
    return []


def _merge_responses_text_config(
    value: Any,
    *,
    response_format: Any | None,
    verbosity: Any | None,
) -> dict[str, Any] | None:
    text_config = dict(value) if isinstance(value, dict) else {}
    if response_format is not None and "format" not in text_config:
        text_config["format"] = response_format
    if verbosity is not None and "verbosity" not in text_config:
        text_config["verbosity"] = verbosity
    return text_config or None


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
    body: dict[str, Any] = {"model": getattr(model_config, "model_name")}
    if max_tokens > 0:
        body["max_output_tokens"] = max_tokens
    thinking = get_thinking_payload(model_config)
    effort_payload = get_effort_payload(model_config)
    reasoning_value = extra_kwargs.pop("reasoning", None)
    if reasoning_value is not None and not isinstance(reasoning_value, dict):
        raise ValueError("Responses reasoning 请求参数必须是对象")
    reasoning = deepcopy(reasoning_value) if isinstance(reasoning_value, dict) else {}
    if effort_payload is not None:
        reasoning["effort"] = effort_payload["effort"]
    if reasoning:
        body["reasoning"] = reasoning
    if thinking is not None:
        body["thinking"] = thinking
    if tools:
        normalized_tools = _normalize_responses_tools(tools, internal_to_api)
        normalized_tool_choice, selected_tool_name = _normalize_responses_tool_choice(
            tool_choice,
            internal_to_api,
            compat_mode=bool(
                getattr(model_config, "responses_tool_choice_compat", False)
            ),
        )
        if selected_tool_name:
            filtered_tools = [
                tool
                for tool in normalized_tools
                if str(tool.get("type", "")).strip().lower() == "function"
                and str(tool.get("name", "")).strip() == selected_tool_name
            ]
            if filtered_tools:
                normalized_tools = filtered_tools
        body["tools"] = normalized_tools
        body["tool_choice"] = normalized_tool_choice

    previous_response_id = ""
    start_index = 0
    stateless_replay = False
    if isinstance(transport_state, dict):
        previous_response_id = str(
            transport_state.get("previous_response_id") or ""
        ).strip()
        stateless_replay = bool(transport_state.get("stateless_replay"))
        try:
            start_index = int(transport_state.get("tool_result_start_index") or 0)
        except Exception:
            start_index = 0
        if start_index < 0:
            start_index = 0

    response_format = extra_kwargs.pop("response_format", None)
    verbosity = extra_kwargs.pop("verbosity", None)
    text_value = extra_kwargs.pop("text", None)
    text_config = _merge_responses_text_config(
        text_value,
        response_format=response_format,
        verbosity=verbosity,
    )
    if text_config is not None:
        body["text"] = text_config
    elif text_value is not None:
        extra_kwargs["text"] = text_value

    include_values = _normalize_include_values(extra_kwargs.pop("include", None))
    reasoning_replay = bool(getattr(model_config, "reasoning_content_replay", True))
    if reasoning_replay:
        if "reasoning.encrypted_content" not in include_values:
            include_values.append("reasoning.encrypted_content")
    else:
        include_values = [
            value for value in include_values if value != "reasoning.encrypted_content"
        ]
    if include_values:
        body["include"] = include_values

    instructions = _messages_to_instruction_text(messages)
    if instructions:
        # previous_response_id 不会继承上一轮 instructions，续轮时也必须显式发送。
        body["instructions"] = instructions

    if previous_response_id and not stateless_replay:
        body["previous_response_id"] = previous_response_id
        body["input"] = _messages_to_responses_input(
            messages[start_index:],
            internal_to_api,
            include_system=True,
            preserve_reasoning=reasoning_replay,
        )
    else:
        body["input"] = _messages_to_responses_input(
            messages,
            internal_to_api,
            include_system=False,
            preserve_reasoning=reasoning_replay,
        )

    body.update(extra_kwargs)
    return body


def _collect_reasoning_text(output: list[dict[str, Any]]) -> str:
    chunks: list[str] = []
    for item in output:
        if not isinstance(item, dict):
            continue
        direct_text = extract_chat_reasoning_text(item)
        if direct_text:
            chunks.append(direct_text)
        if item.get("type") != "reasoning":
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
    assistant_phase: str | None = None
    tool_calls: list[dict[str, Any]] = []
    for item in output:
        if not isinstance(item, dict):
            continue
        item_type = str(item.get("type", "")).strip().lower()
        if (
            item_type == "message"
            and str(item.get("role", "")).strip().lower() == "assistant"
        ):
            if assistant_phase is None and item.get("phase") is not None:
                assistant_phase = str(item.get("phase"))
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
            else:
                text = _stringify_content(content)
                if text:
                    assistant_texts.append(text)
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

    content = "\n".join(text for text in assistant_texts if text)
    if not content and "output_text" in result:
        content = str(result["output_text"])

    message: dict[str, Any] = {
        "role": "assistant",
        "content": content,
    }
    if assistant_phase is not None:
        message["phase"] = assistant_phase
    output_items = _copy_responses_output_items(output, api_to_internal)
    if output_items:
        message[RESPONSES_OUTPUT_ITEMS_KEY] = output_items
    # Official Responses uses root-level `reasoning` for request configuration,
    # not generated reasoning content. Native content lives in output items.
    root_reasoning_fields = {
        key: deepcopy(result[key])
        for key in _RESPONSES_COMPAT_REASONING_FIELDS
        if key in result and result[key] is not None
    }
    if root_reasoning_fields:
        message[RESPONSES_REASONING_REPLAY_KEY] = root_reasoning_fields
    reasoning_content = _collect_reasoning_text(output)
    if not reasoning_content:
        reasoning_content = extract_chat_reasoning_text(root_reasoning_fields)
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
