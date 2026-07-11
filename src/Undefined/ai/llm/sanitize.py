"""LLM 出站请求清洗与工具名规范化。

负责工具 schema/description 清洗、历史消息字段剥离、工具名 API 编码；
不发起 HTTP 请求，也不解析模型响应。
"""

from __future__ import annotations

import hashlib
import logging
import re
from copy import deepcopy
from typing import Any

from Undefined.ai.llm.types import ModelConfig
from Undefined.ai.transports.openai_transport import (
    CHAT_REASONING_REPLAY_KEY,
    CHAT_REASONING_WIRE_FIELDS,
    RESPONSES_REASONING_REPLAY_KEY,
)
from Undefined.config import Config, get_config
from Undefined.utils.tool_calls import normalize_tool_arguments_json

logger = logging.getLogger(__name__)

_DEFAULT_TOOLS_DESCRIPTION_MAX_LEN = 1024
_DEFAULT_TOOLS_DESCRIPTION_PREVIEW_LEN = 160

_DEFAULT_TOOL_NAME_DOT_DELIMITER = "-_-"
_TOOL_NAME_MAX_LEN = 64
_TOOL_NAME_ALLOWED_RE = re.compile(r"^[a-zA-Z0-9_-]+$")

_CHAT_COMPLETION_STRIP_THINKING_KEYS: frozenset[str] = frozenset(
    ("thinking", "reasoning", "chain_of_thought", "cot", "thoughts")
)
CHAT_COMPLETION_INTERNAL_MESSAGE_KEYS: frozenset[str] = frozenset(
    (
        "reasoning_content",
        "reasoning_details",
        "encrypted_content",
        *_CHAT_COMPLETION_STRIP_THINKING_KEYS,
        CHAT_REASONING_REPLAY_KEY,
        RESPONSES_REASONING_REPLAY_KEY,
        "_responses_output_items",
        "_anthropic_content_blocks",
        "phase",
    )
)


def _get_runtime_config() -> Config | None:
    try:
        return get_config(strict=False)
    except Exception:
        return None


def _tool_name_dot_delimiter() -> str:
    runtime_config = _get_runtime_config()
    value = (
        getattr(runtime_config, "tools_dot_delimiter", None) if runtime_config else None
    )
    text = str(value).strip() if value is not None else _DEFAULT_TOOL_NAME_DOT_DELIMITER
    if not text:
        return _DEFAULT_TOOL_NAME_DOT_DELIMITER
    if "." in text:
        return _DEFAULT_TOOL_NAME_DOT_DELIMITER
    if not _TOOL_NAME_ALLOWED_RE.match(text):
        return _DEFAULT_TOOL_NAME_DOT_DELIMITER
    # 保持较短长度，避免工具名被服务端截断。
    if len(text) > 16:
        return text[:16]
    return text


def _hash8(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8"), usedforsecurity=False).hexdigest()[:8]


def _encode_tool_name_for_api(tool_name: str) -> str:
    """将内部工具名编码为服务端可接受的 function.name。

    - 将 '.' 替换为 '-_-'（保留工具集命名语义）
    - 其他不允许字符替换为 '_'
    - 强制最大长度（<=64），超长时追加稳定哈希
    """
    raw = str(tool_name or "").strip()
    if not raw:
        return "tool"

    # 保留工具集分隔语义：category.tool -> category<delimiter>tool
    encoded = raw.replace(".", _tool_name_dot_delimiter())

    # 替换其他不允许字符。
    cleaned_chars: list[str] = []
    for ch in encoded:
        if ch.isalnum() or ch in {"_", "-"}:
            cleaned_chars.append(ch)
        else:
            cleaned_chars.append("_")
    encoded = "".join(cleaned_chars)

    if not encoded:
        encoded = "tool"

    if len(encoded) > _TOOL_NAME_MAX_LEN:
        suffix = "_" + _hash8(raw)
        prefix_len = max(1, _TOOL_NAME_MAX_LEN - len(suffix))
        encoded = encoded[:prefix_len] + suffix

    # 最后兜底校验（理论上应始终通过）
    if not _TOOL_NAME_ALLOWED_RE.match(encoded):
        suffix = "_" + _hash8(raw)
        encoded = re.sub(r"[^a-zA-Z0-9_-]", "_", encoded)
        if len(encoded) > _TOOL_NAME_MAX_LEN:
            encoded = encoded[: _TOOL_NAME_MAX_LEN - len(suffix)] + suffix
        if not encoded:
            encoded = "tool" + suffix

    return encoded


def sanitize_openai_tool_names_in_request(
    request_body: dict[str, Any],
) -> tuple[dict[str, str], dict[str, str]]:
    """将 request_body 的 tools/messages 工具名改写为服务端可接受的名称。

    Returns:
        (api_to_internal, internal_to_api) 映射表。

    Notes:
        - 仅保证 tools schema 中出现的名称可逆映射。
        - 历史消息中的工具调用会尽力重写。
    """
    tools = request_body.get("tools")
    if not isinstance(tools, list) or not tools:
        return {}, {}

    internal_to_api: dict[str, str] = {}
    api_to_internal: dict[str, str] = {}
    used_api: set[str] = set()

    new_tools: list[dict[str, Any]] = []
    for tool in tools:
        if not isinstance(tool, dict):
            new_tools.append(tool)
            continue
        function = tool.get("function")
        if not isinstance(function, dict):
            new_tools.append(tool)
            continue
        internal_name = str(function.get("name", "") or "")
        if not internal_name:
            new_tools.append(tool)
            continue

        # 稳定编码；如发生冲突则追加后缀。
        base_api_name = _encode_tool_name_for_api(internal_name)
        api_name = base_api_name
        if api_name in used_api and api_to_internal.get(api_name) != internal_name:
            suffix = "_" + _hash8(internal_name)
            prefix_len = max(1, _TOOL_NAME_MAX_LEN - len(suffix))
            api_name = base_api_name[:prefix_len] + suffix
        if api_name in used_api and api_to_internal.get(api_name) != internal_name:
            # 极少数冲突兜底：加入索引避免重复。
            suffix = "_" + _hash8(f"{internal_name}:{len(used_api)}")
            prefix_len = max(1, _TOOL_NAME_MAX_LEN - len(suffix))
            api_name = base_api_name[:prefix_len] + suffix

        used_api.add(api_name)
        internal_to_api[internal_name] = api_name
        api_to_internal[api_name] = internal_name

        if api_name != internal_name:
            tool = dict(tool)
            function = dict(function)
            function["name"] = api_name
            tool["function"] = function
        new_tools.append(tool)

    request_body["tools"] = new_tools

    # 尽力重写历史消息中的工具名。
    messages = request_body.get("messages")
    if isinstance(messages, list) and messages:
        new_messages: list[dict[str, Any]] = []
        changed = False
        for message in messages:
            if not isinstance(message, dict):
                new_messages.append(message)
                continue

            new_message = message

            msg_name = message.get("name")
            if isinstance(msg_name, str) and msg_name:
                mapped = internal_to_api.get(msg_name)
                if mapped and mapped != msg_name:
                    if new_message is message:
                        new_message = dict(message)
                    new_message["name"] = mapped
                    changed = True
                elif (not _TOOL_NAME_ALLOWED_RE.match(msg_name)) or (
                    len(msg_name) > _TOOL_NAME_MAX_LEN
                ):
                    # 即便名称不在 schema 映射中，也尽量保证请求合法（如工具被重命名/移除）。
                    safe = _encode_tool_name_for_api(msg_name)
                    if safe != msg_name:
                        if new_message is message:
                            new_message = dict(message)
                        new_message["name"] = safe
                        changed = True

            tool_calls = message.get("tool_calls")
            # 无 tool_calls 与有 tool_calls 走不同分支
            if isinstance(tool_calls, list) and tool_calls:
                new_tool_calls: list[Any] = []
                tool_calls_changed = False
                # 逐个处理模型返回的 tool_call
                for tool_call in tool_calls:
                    if not isinstance(tool_call, dict):
                        new_tool_calls.append(tool_call)
                        continue
                    function = tool_call.get("function")
                    if not isinstance(function, dict):
                        new_tool_calls.append(tool_call)
                        continue
                    fname = function.get("name")
                    if not isinstance(fname, str) or not fname:
                        new_tool_calls.append(tool_call)
                        continue
                    mapped = internal_to_api.get(fname)
                    safe_name = mapped or _encode_tool_name_for_api(fname)
                    if safe_name != fname:
                        tool_calls_changed = True
                        new_tool_call = dict(tool_call)
                        new_function = dict(function)
                        new_function["name"] = safe_name
                        new_tool_call["function"] = new_function
                        new_tool_calls.append(new_tool_call)
                    else:
                        new_tool_calls.append(tool_call)

                # 无 tool_calls 与有 tool_calls 走不同分支
                if tool_calls_changed:
                    if new_message is message:
                        new_message = dict(message)
                    new_message["tool_calls"] = new_tool_calls
                    changed = True

            new_messages.append(new_message)

        if changed:
            request_body["messages"] = new_messages

    return api_to_internal, internal_to_api


def _tools_sanitize_enabled() -> bool:
    # 历史配置项 tools.sanitize 已迁移为 tools.dot_delimiter。
    # 为兼容严格网关，description 的 schema 清洗默认始终开启。
    return True


def tools_sanitize_verbose() -> bool:
    """是否输出工具 schema 清洗的详细日志。"""
    runtime_config = _get_runtime_config()
    if runtime_config is not None:
        return bool(runtime_config.tools_sanitize_verbose)
    return False


def tools_description_max_len() -> int:
    """返回工具 description 允许的最大长度。"""
    runtime_config = _get_runtime_config()
    if runtime_config is None:
        return _DEFAULT_TOOLS_DESCRIPTION_MAX_LEN
    value = runtime_config.tools_description_max_len
    return value if value > 0 else _DEFAULT_TOOLS_DESCRIPTION_MAX_LEN


def tools_description_truncate_enabled() -> bool:
    """是否启用工具 description 截断。"""
    runtime_config = _get_runtime_config()
    if runtime_config is None:
        return False
    return bool(runtime_config.tools_description_truncate_enabled)


def _clean_control_chars(text: str) -> str:
    """将 ASCII 控制字符替换为空格。"""
    return "".join(" " if ord(ch) < 32 or ord(ch) == 127 else ch for ch in text)


def desc_preview(text: str) -> str:
    """生成工具 description 的日志预览片段。"""
    runtime_config = _get_runtime_config()
    if runtime_config is None:
        preview_len = _DEFAULT_TOOLS_DESCRIPTION_PREVIEW_LEN
    else:
        preview_len = runtime_config.tools_description_preview_len
        if preview_len <= 0:
            preview_len = _DEFAULT_TOOLS_DESCRIPTION_PREVIEW_LEN
    return text[:preview_len] + ("…" if len(text) > preview_len else "")


def _normalize_tool_description(
    description: Any,
    tool_name: str,
    max_len: int,
    truncate_enabled: bool,
) -> str:
    """规范化工具 function.description，适配更严格的 OpenAI 兼容服务。"""
    if description is None:
        normalized = ""
    elif isinstance(description, str):
        normalized = description
    else:
        normalized = str(description)

    normalized = _clean_control_chars(normalized)
    normalized = " ".join(normalized.split())
    normalized = normalized.strip()
    if not normalized:
        normalized = f"Tool function {tool_name}"
    if truncate_enabled and len(normalized) > max_len:
        normalized = normalized[:max_len].rstrip()
    return normalized


def sanitize_openai_tools(
    tools: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int, list[dict[str, Any]]]:
    """清洗 tools schema，避免严格网关因非法 description 返回 400。"""
    if not tools or not _tools_sanitize_enabled():
        return tools, 0, []

    max_len = tools_description_max_len()
    truncate_enabled = tools_description_truncate_enabled()
    changed = 0
    changes: list[dict[str, Any]] = []
    sanitized: list[dict[str, Any]] = []
    for idx, tool in enumerate(tools):
        if not isinstance(tool, dict):
            sanitized.append(tool)
            continue
        function = tool.get("function")
        if not isinstance(function, dict):
            sanitized.append(tool)
            continue
        name = function.get("name", "")
        old_desc = function.get("description")
        old_desc_str = (
            ""
            if old_desc is None
            else (old_desc if isinstance(old_desc, str) else str(old_desc))
        )
        new_desc = _normalize_tool_description(
            old_desc,
            str(name),
            max_len,
            truncate_enabled,
        )

        if old_desc_str != new_desc:
            reasons: list[str] = []
            if not isinstance(old_desc, str):
                reasons.append("non_string")
            if any(ord(ch) < 32 or ord(ch) == 127 for ch in old_desc_str):
                reasons.append("control_chars")
            if "\n" in old_desc_str or "\r" in old_desc_str or "\t" in old_desc_str:
                reasons.append("whitespace")
            if not old_desc_str.strip():
                reasons.append("empty")
            if (
                truncate_enabled
                and len(new_desc) >= max_len
                and len(old_desc_str) > len(new_desc)
            ):
                reasons.append("truncated")

            tool = dict(tool)
            function = dict(function)
            function["description"] = new_desc
            tool["function"] = function
            changed += 1
            changes.append(
                {
                    "index": idx,
                    "name": str(name),
                    "old_len": len(old_desc_str),
                    "new_len": len(new_desc),
                    "old_preview": desc_preview(_clean_control_chars(old_desc_str)),
                    "new_preview": desc_preview(new_desc),
                    "reasons": reasons,
                }
            )
        sanitized.append(tool)
    return sanitized, changed, changes


def sanitize_openai_messages_tool_arguments(
    messages: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    """将 messages[].tool_calls[].function.arguments 规范为严格 JSON 字符串。"""
    if not messages:
        return messages, 0

    changed = 0
    sanitized_messages: list[dict[str, Any]] = []
    for message in messages:
        if not isinstance(message, dict):
            sanitized_messages.append(message)
            continue

        tool_calls = message.get("tool_calls")
        # 无 tool_calls 与有 tool_calls 走不同分支
        if not isinstance(tool_calls, list) or not tool_calls:
            sanitized_messages.append(message)
            continue

        tool_calls_changed = False
        sanitized_tool_calls: list[Any] = []
        # 逐个处理模型返回的 tool_call
        for tool_call in tool_calls:
            if not isinstance(tool_call, dict):
                sanitized_tool_calls.append(tool_call)
                continue
            function = tool_call.get("function")
            if not isinstance(function, dict):
                sanitized_tool_calls.append(tool_call)
                continue

            old_args = function.get("arguments")
            new_args = normalize_tool_arguments_json(old_args)
            if isinstance(old_args, str) and old_args == new_args:
                sanitized_tool_calls.append(tool_call)
                continue

            tool_calls_changed = True
            changed += 1
            new_tool_call = dict(tool_call)
            new_function = dict(function)
            new_function["arguments"] = new_args
            new_tool_call["function"] = new_function
            sanitized_tool_calls.append(new_tool_call)

        # 无 tool_calls 与有 tool_calls 走不同分支
        if tool_calls_changed:
            new_message = dict(message)
            new_message["tool_calls"] = sanitized_tool_calls
            sanitized_messages.append(new_message)
        else:
            sanitized_messages.append(message)

    return sanitized_messages, changed


def sanitize_chat_completion_messages(
    messages: list[dict[str, Any]],
    *,
    preserve_reasoning_content: bool = False,
) -> tuple[list[dict[str, Any]], int, dict[str, int]]:
    """移除 Chat Completions 非标准消息字段。

    本地历史里允许保留 reasoning_content 等兼容字段用于日志/回放；
    发往上游时默认剥离。``preserve_reasoning_content=True`` 时保留
    原始推理字段供多轮 CoT 续传，仍剥离其它内部字段。
    """
    if not messages:
        return messages, 0, {}

    changed = 0
    stripped_fields: dict[str, int] = {}
    sanitized_messages: list[dict[str, Any]] = []
    for message in messages:
        if not isinstance(message, dict):
            sanitized_messages.append(message)
            continue

        sanitized_message = message
        preserved_reasoning_fields: set[str] = set()
        if preserve_reasoning_content:
            raw_reasoning = message.get(CHAT_REASONING_REPLAY_KEY)
            if isinstance(raw_reasoning, dict):
                sanitized_message = dict(message)
                for key, value in raw_reasoning.items():
                    field_name = str(key)
                    if field_name not in CHAT_REASONING_WIRE_FIELDS:
                        continue
                    sanitized_message[field_name] = deepcopy(value)
                    preserved_reasoning_fields.add(field_name)
            else:
                preserved_reasoning_fields.update(
                    key
                    for key in CHAT_REASONING_WIRE_FIELDS
                    if key in message and message[key] is not None
                )
        removed = False
        for key in CHAT_COMPLETION_INTERNAL_MESSAGE_KEYS:
            if preserve_reasoning_content and key in preserved_reasoning_fields:
                continue
            if key not in sanitized_message:
                continue
            if sanitized_message is message:
                sanitized_message = dict(message)
            sanitized_message.pop(key, None)
            stripped_fields[key] = stripped_fields.get(key, 0) + 1
            removed = True

        if removed:
            changed += 1
        sanitized_messages.append(sanitized_message)

    return sanitized_messages, changed, stripped_fields


def relocate_system_to_first_user(
    messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """将 system/developer 消息合并注入首条 user（OpenAI Chat 适配）。"""
    if not messages:
        return messages

    system_parts: list[str] = []
    remaining: list[dict[str, Any]] = []
    for message in messages:
        if not isinstance(message, dict):
            remaining.append(message)
            continue
        role = str(message.get("role") or "").strip().lower()
        if role in ("system", "developer"):
            content = message.get("content")
            if content is not None:
                text = content if isinstance(content, str) else str(content)
                if text.strip():
                    system_parts.append(text.strip())
            continue
        remaining.append(message)

    if not system_parts:
        return messages

    merged_system = "\n\n".join(system_parts)
    first_user_idx: int | None = None
    for idx, message in enumerate(remaining):
        if (
            isinstance(message, dict)
            and str(message.get("role") or "").strip().lower() == "user"
        ):
            first_user_idx = idx
            break

    if first_user_idx is None:
        remaining.insert(0, {"role": "user", "content": merged_system})
        return remaining

    first_user = dict(remaining[first_user_idx])
    old_content = first_user.get("content")
    old_text = (
        old_content
        if isinstance(old_content, str)
        else (str(old_content) if old_content is not None else "")
    )
    if old_text.strip():
        first_user["content"] = f"{merged_system}\n\n{old_text}"
    else:
        first_user["content"] = merged_system
    updated = list(remaining)
    updated[first_user_idx] = first_user
    return updated


def prepare_chat_completion_messages(
    model_config: ModelConfig,
    messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """按模型配置整理 Chat Completions 出站消息。"""
    preserve_reasoning = bool(getattr(model_config, "reasoning_content_replay", True))
    prepared, _, _ = sanitize_chat_completion_messages(
        messages,
        preserve_reasoning_content=preserve_reasoning,
    )
    if bool(getattr(model_config, "system_prompt_as_user", False)):
        prepared = relocate_system_to_first_user(prepared)
    return prepared
