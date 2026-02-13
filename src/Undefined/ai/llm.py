"""LLM 模型请求处理。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import time
from datetime import datetime
from typing import Any
from urllib.parse import parse_qsl, urlsplit, urlunsplit

import httpx
from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI

from Undefined.ai.parsing import extract_choices_content
from Undefined.ai.tokens import TokenCounter
from Undefined.config import (
    ChatModelConfig,
    VisionModelConfig,
    AgentModelConfig,
    SecurityModelConfig,
    Config,
    get_config,
)
from Undefined.token_usage_storage import TokenUsageStorage, TokenUsage
from Undefined.utils.logging import log_debug_json, redact_string
from Undefined.utils.tool_calls import normalize_tool_arguments_json

logger = logging.getLogger(__name__)

ModelConfig = (
    ChatModelConfig | VisionModelConfig | AgentModelConfig | SecurityModelConfig
)

__all__ = ["ModelRequester", "build_request_body", "ModelConfig"]

_CHAT_COMPLETIONS_KNOWN_FIELDS: set[str] = {
    "model",
    "messages",
    "max_tokens",
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
}

_THINKING_KEYS: tuple[str, ...] = (
    "thinking",
    "reasoning",
    "reasoning_content",
    "chain_of_thought",
    "cot",
    "thoughts",
)

_DEFAULT_TOOLS_DESCRIPTION_MAX_LEN = 1024
_TOOLS_PARAM_INDEX_RE = re.compile(r"Tools\[(\d+)\]", re.IGNORECASE)
_DEFAULT_TOOLS_DESCRIPTION_PREVIEW_LEN = 160

_DEFAULT_TOOL_NAME_DOT_DELIMITER = "-_-"
_TOOL_NAME_MAX_LEN = 64
_TOOL_NAME_ALLOWED_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


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


def _sanitize_openai_tool_names_in_request(
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

            # 重写 role=tool 的 name 字段（可选字段）。
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
            if isinstance(tool_calls, list) and tool_calls:
                new_tool_calls: list[Any] = []
                tool_calls_changed = False
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

                if tool_calls_changed:
                    if new_message is message:
                        new_message = dict(message)
                    new_message["tool_calls"] = new_tool_calls
                    changed = True

            new_messages.append(new_message)

        if changed:
            request_body["messages"] = new_messages

    return api_to_internal, internal_to_api


def _get_runtime_config() -> Config | None:
    try:
        return get_config(strict=False)
    except Exception:
        return None


def _split_chat_completion_params(
    body: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    known: dict[str, Any] = {}
    extra: dict[str, Any] = {}
    for key, value in body.items():
        if key in _CHAT_COMPLETIONS_KNOWN_FIELDS:
            known[key] = value
        else:
            extra[key] = value
    return known, extra


def _is_deepseek_provider(model_config: ModelConfig) -> bool:
    model_name = str(getattr(model_config, "model_name", "") or "").lower()
    if model_name.startswith("deepseek"):
        return True
    api_url = str(getattr(model_config, "api_url", "") or "").lower()
    return "deepseek" in api_url


def _normalize_thinking_override(
    value: Any, model_config: ModelConfig
) -> dict[str, Any] | None:
    if value is None:
        return None

    is_deepseek = _is_deepseek_provider(model_config)

    if isinstance(value, dict):
        raw_type = value.get("type")
        if isinstance(raw_type, str):
            type_value = raw_type.strip().lower()
            if type_value in {"enabled", "disabled"}:
                return {"type": type_value} if is_deepseek else dict(value)

        raw_enabled = value.get("enabled")
        if isinstance(raw_enabled, bool):
            type_value = "enabled" if raw_enabled else "disabled"
            if is_deepseek:
                return {"type": type_value}
            normalized = dict(value)
            normalized.pop("enabled", None)
            normalized["type"] = type_value
            return normalized

        return None

    if isinstance(value, bool):
        return {"type": "enabled" if value else "disabled"}

    if isinstance(value, str):
        type_value = value.strip().lower()
        if type_value in {"enabled", "disabled"}:
            return {"type": type_value}

    return None


def _tools_sanitize_enabled() -> bool:
    # 历史配置项 tools.sanitize 已迁移为 tools.dot_delimiter。
    # 为兼容严格网关，description 的 schema 清洗默认始终开启。
    return True


def _tools_sanitize_verbose() -> bool:
    runtime_config = _get_runtime_config()
    if runtime_config is not None:
        return bool(runtime_config.tools_sanitize_verbose)
    return False


def _tools_description_max_len() -> int:
    runtime_config = _get_runtime_config()
    if runtime_config is None:
        return _DEFAULT_TOOLS_DESCRIPTION_MAX_LEN
    value = runtime_config.tools_description_max_len
    return value if value > 0 else _DEFAULT_TOOLS_DESCRIPTION_MAX_LEN


def _tools_description_truncate_enabled() -> bool:
    runtime_config = _get_runtime_config()
    if runtime_config is None:
        return False
    return bool(runtime_config.tools_description_truncate_enabled)


def _clean_control_chars(text: str) -> str:
    """将 ASCII 控制字符替换为空格。"""
    return "".join(" " if ord(ch) < 32 or ord(ch) == 127 else ch for ch in text)


def _desc_preview(text: str) -> str:
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


def _sanitize_openai_tools(
    tools: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int, list[dict[str, Any]]]:
    """Sanitize tools schema to avoid 400s on strict providers (e.g., invalid description)."""
    if not tools or not _tools_sanitize_enabled():
        return tools, 0, []

    max_len = _tools_description_max_len()
    truncate_enabled = _tools_description_truncate_enabled()
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
                    "old_preview": _desc_preview(_clean_control_chars(old_desc_str)),
                    "new_preview": _desc_preview(new_desc),
                    "reasons": reasons,
                }
            )
        sanitized.append(tool)
    return sanitized, changed, changes


def _sanitize_openai_messages_tool_arguments(
    messages: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    """Sanitize messages[].tool_calls[].function.arguments to strict JSON strings.

    Some OpenAI-compatible providers reject non-JSON `function.arguments` in the
    request body (even though upstream OpenAI treats it as an opaque string).
    This primarily affects conversations that include historical tool_calls.
    """
    if not messages:
        return messages, 0

    changed = 0
    sanitized_messages: list[dict[str, Any]] = []
    for message in messages:
        if not isinstance(message, dict):
            sanitized_messages.append(message)
            continue

        tool_calls = message.get("tool_calls")
        if not isinstance(tool_calls, list) or not tool_calls:
            sanitized_messages.append(message)
            continue

        tool_calls_changed = False
        sanitized_tool_calls: list[Any] = []
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

        if tool_calls_changed:
            new_message = dict(message)
            new_message["tool_calls"] = sanitized_tool_calls
            sanitized_messages.append(new_message)
        else:
            sanitized_messages.append(message)

    return sanitized_messages, changed


def _stringify_thinking_list(value: list[Any]) -> str:
    """将列表类型的思维链转换为字符串。

    Args:
        value: 思维链列表

    Returns:
        格式化后的字符串
    """
    parts = [_stringify_thinking(item) for item in value]
    return "\n".join([part for part in parts if part])


def _stringify_thinking_dict(value: dict[str, Any]) -> str:
    """将字典类型的思维链转换为字符串。

    Args:
        value: 思维链字典

    Returns:
        格式化后的字符串
    """
    content = value.get("content")
    if isinstance(content, str) and content:
        return content
    return str(value)


def _stringify_thinking(value: Any) -> str:
    """将思维链值转换为字符串。

    Args:
        value: 思维链值（可以是 None、字符串、列表或字典）

    Returns:
        格式化后的字符串
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return _stringify_thinking_list(value)
    if isinstance(value, dict):
        return _stringify_thinking_dict(value)
    return str(value)


def _extract_from_message(message: dict[str, Any]) -> str:
    """从 message 对象中提取思维链内容。

    Args:
        message: message 对象

    Returns:
        思维链内容字符串
    """
    if not isinstance(message, dict):
        return ""
    for key in _THINKING_KEYS:
        if key in message:
            return _stringify_thinking(message.get(key))
    return ""


def _extract_from_choice(choice: dict[str, Any]) -> str:
    """从 choice 对象中提取思维链内容。

    Args:
        choice: choice 对象

    Returns:
        思维链内容字符串
    """
    if not isinstance(choice, dict):
        return ""

    # 优先从 message 中提取
    message = choice.get("message")
    if isinstance(message, dict):
        thinking = _extract_from_message(message)
        if thinking:
            return thinking

    # 尝试从 choice 直接提取
    for key in _THINKING_KEYS:
        if key in choice:
            return _stringify_thinking(choice.get(key))

    return ""


def _extract_from_choices(choices: list[Any]) -> str:
    """从 choices 列表中提取思维链内容。

    Args:
        choices: choices 列表

    Returns:
        思维链内容字符串
    """
    if not isinstance(choices, list) or not choices:
        return ""
    choice = choices[0]
    return _extract_from_choice(choice)


def _extract_from_result(result: dict[str, Any]) -> str:
    """直接从结果对象中提取思维链内容。

    Args:
        result: API 响应结果

    Returns:
        思维链内容字符串
    """
    for key in _THINKING_KEYS:
        if key in result:
            return _stringify_thinking(result.get(key))
    return ""


def _extract_thinking_content(result: dict[str, Any]) -> str:
    """从 API 响应中提取思维链内容。

    提取优先级：
    1. 从 choices[0].message 中提取
    2. 从 choices[0] 直接提取
    3. 从响应根对象中提取

    Args:
        result: API 响应结果

    Returns:
        思维链内容字符串
    """
    # 尝试从 choices 中提取
    choices = result.get("choices")
    if isinstance(choices, list):
        thinking = _extract_from_choices(choices)
        if thinking:
            return thinking

    # 尝试从响应根对象中提取
    return _extract_from_result(result)


def _normalize_openai_base_url(
    api_url: str,
) -> tuple[str, dict[str, object] | None, bool]:
    """将旧式 /chat/completions URL 归一化为 OpenAI SDK 需要的 base_url。

    兼容策略（B）：如果发现 api_url 末尾包含 /chat/completions，则自动裁剪为 base_url，
    以便统一走 OpenAI SDK，并给出弃用警告。
    """
    try:
        parts = urlsplit(api_url)
    except Exception:
        return api_url, None, False

    path = parts.path or ""
    trimmed_path = path.rstrip("/")
    suffix = "/chat/completions"
    if not trimmed_path.endswith(suffix):
        return api_url, None, False

    new_path = trimmed_path[: -len(suffix)]
    default_query: dict[str, object] | None = None
    if parts.query:
        default_query = {
            k: v for k, v in parse_qsl(parts.query, keep_blank_values=True)
        }
    normalized = urlunsplit(parts._replace(path=new_path, query="", fragment=""))
    return normalized, default_query, True


class ModelRequester:
    """统一的模型请求封装。"""

    def __init__(
        self,
        http_client: httpx.AsyncClient,
        token_usage_storage: TokenUsageStorage,
    ) -> None:
        self._http_client = http_client
        self._token_usage_storage = token_usage_storage
        self._openai_clients: dict[
            tuple[str, str, tuple[tuple[str, str], ...] | None], AsyncOpenAI
        ] = {}
        self._token_counters: dict[str, TokenCounter] = {}
        self._warned_legacy_api_urls: set[str] = set()
        self._background_tasks: set[asyncio.Task[Any]] = set()

    async def request(
        self,
        model_config: ModelConfig,
        messages: list[dict[str, Any]],
        max_tokens: int = 8192,
        call_type: str = "chat",
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str = "auto",
        **kwargs: Any,
    ) -> dict[str, Any]:
        """发送请求到模型 API。"""
        start_time = time.perf_counter()
        ds_cot_enabled = getattr(model_config, "deepseek_new_cot_support", False)
        messages_for_api, tool_args_fixed = _sanitize_openai_messages_tool_arguments(
            messages
        )
        if tool_args_fixed and logger.isEnabledFor(logging.INFO):
            logger.info(
                "[messages.sanitize] tool_args_fixed=%s messages=%s",
                tool_args_fixed,
                len(messages_for_api),
            )
        request_body = build_request_body(
            model_config=model_config,
            messages=messages_for_api,
            max_tokens=max_tokens,
            tools=tools,
            tool_choice=tool_choice,
            **kwargs,
        )

        api_to_internal: dict[str, str] = {}
        internal_to_api: dict[str, str] = {}
        if isinstance(request_body.get("tools"), list):
            api_to_internal, internal_to_api = _sanitize_openai_tool_names_in_request(
                request_body
            )

        if "tools" in request_body and isinstance(request_body.get("tools"), list):
            sanitized_tools, changed_count, changes = _sanitize_openai_tools(
                request_body["tools"]
            )
            request_body["tools"] = sanitized_tools
            if changed_count and logger.isEnabledFor(logging.INFO):
                logger.info(
                    "[tools.sanitize] changed=%s total=%s truncate_enabled=%s max_desc_len=%s",
                    changed_count,
                    len(sanitized_tools),
                    _tools_description_truncate_enabled(),
                    _tools_description_max_len(),
                )
                if _tools_sanitize_verbose():
                    for change in changes:
                        logger.info(
                            "[tools.sanitize.item] index=%s name=%s reasons=%s old_len=%s new_len=%s old=%s new=%s",
                            change.get("index"),
                            change.get("name"),
                            ",".join(change.get("reasons", [])),
                            change.get("old_len"),
                            change.get("new_len"),
                            change.get("old_preview"),
                            change.get("new_preview"),
                        )

        try:
            if ds_cot_enabled and logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "[DeepSeek CoT] enabled=%s type=%s model=%s thinking_enabled=%s tools=%s messages=%s",
                    ds_cot_enabled,
                    call_type,
                    model_config.model_name,
                    getattr(model_config, "thinking_enabled", False),
                    bool(tools),
                    len(messages),
                )

            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "[API请求] type=%s model=%s url=%s max_tokens=%s tools=%s tool_choice=%s messages=%s",
                    call_type,
                    model_config.model_name,
                    model_config.api_url,
                    max_tokens,
                    bool(tools),
                    tool_choice,
                    len(messages),
                )
                log_debug_json(logger, "[API请求体]", request_body)

            result = await self._request_with_openai(model_config, request_body)
            result = self._normalize_result(result)
            if api_to_internal:
                result["_tool_name_map"] = {
                    "api_to_internal": api_to_internal,
                    "internal_to_api": internal_to_api,
                    "dot_delimiter": _tool_name_dot_delimiter(),
                }
            duration = time.perf_counter() - start_time

            usage = result.get("usage", {}) or {}
            prompt_tokens = int(usage.get("prompt_tokens", 0) or 0)
            completion_tokens = int(usage.get("completion_tokens", 0) or 0)
            total_tokens = int(usage.get("total_tokens", 0) or 0)
            if total_tokens == 0 and (prompt_tokens or completion_tokens):
                total_tokens = prompt_tokens + completion_tokens
            if total_tokens == 0:
                prompt_tokens, completion_tokens, total_tokens = self._estimate_usage(
                    model_config.model_name, messages_for_api, result
                )

            logger.info(
                f"[API响应] {call_type} 完成: 耗时={duration:.2f}s, "
                f"Tokens={total_tokens} (P:{prompt_tokens} + C:{completion_tokens}), "
                f"模型={model_config.model_name}"
            )

            if logger.isEnabledFor(logging.DEBUG):
                log_debug_json(logger, "[API响应体]", result)

            self._maybe_log_thinking(result, call_type, model_config.model_name)

            # 创建后台任务记录 token 使用情况，并保存引用防止被垃圾回收
            task = asyncio.create_task(
                self._token_usage_storage.record(
                    TokenUsage(
                        timestamp=datetime.now().isoformat(),
                        model_name=model_config.model_name,
                        prompt_tokens=prompt_tokens,
                        completion_tokens=completion_tokens,
                        total_tokens=total_tokens,
                        duration_seconds=duration,
                        call_type=call_type,
                        success=True,
                    )
                )
            )
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)

            return result
        except APIStatusError as exc:
            response = exc.response
            try:
                body = (
                    json.dumps(exc.body, ensure_ascii=False, default=str)
                    if exc.body is not None
                    else ""
                )
            except Exception:
                body = str(exc.body)
            if (
                exc.status_code == 400
                and isinstance(exc.body, dict)
                and isinstance(exc.body.get("error"), dict)
            ):
                param = exc.body.get("error", {}).get("param")
                if isinstance(param, str):
                    match = _TOOLS_PARAM_INDEX_RE.search(param)
                    if match and isinstance(request_body.get("tools"), list):
                        try:
                            idx = int(match.group(1))
                        except ValueError:
                            idx = -1
                        if 0 <= idx < len(request_body["tools"]):
                            tool = request_body["tools"][idx]
                            tool_name = (
                                tool.get("function", {}).get("name")
                                if isinstance(tool, dict)
                                else ""
                            )
                            desc_len: int | None = None
                            desc_preview = ""
                            if isinstance(tool, dict):
                                function = tool.get("function", {})
                                if isinstance(function, dict):
                                    desc = function.get("description")
                                    if desc is not None:
                                        desc_str = (
                                            desc if isinstance(desc, str) else str(desc)
                                        )
                                        desc_len = len(desc_str)
                                        desc_preview = _desc_preview(desc_str)
                            logger.error(
                                "[tools.invalid] index=%s name=%s desc_len=%s desc=%s param=%s",
                                idx,
                                tool_name,
                                desc_len,
                                desc_preview,
                                param,
                            )
            logger.error(
                "[API响应错误] status=%s request_id=%s url=%s body=%s",
                exc.status_code,
                exc.request_id or "",
                response.request.url,
                redact_string(body),
            )
            raise
        except (APIConnectionError, APITimeoutError) as exc:
            logger.error("[API连接错误] type=%s message=%s", type(exc).__name__, exc)
            raise
        except Exception as exc:
            logger.exception(f"[model.request.error] {call_type} 调用失败: {exc}")
            raise

    def _thinking_logging_enabled(self) -> bool:
        runtime_config = _get_runtime_config()
        if runtime_config is None:
            return True
        return bool(runtime_config.log_thinking)

    def _maybe_log_thinking(
        self, result: dict[str, Any], call_type: str, model_name: str
    ) -> None:
        if not self._thinking_logging_enabled():
            return
        thinking = _extract_thinking_content(result)
        if thinking:
            logger.info(
                "[思维链] type=%s model=%s content=%s",
                call_type,
                model_name,
                redact_string(thinking),
            )

    async def _request_with_openai(
        self, model_config: ModelConfig, request_body: dict[str, Any]
    ) -> dict[str, Any]:
        base_url, default_query, changed = _normalize_openai_base_url(
            model_config.api_url
        )
        if changed and model_config.api_url not in self._warned_legacy_api_urls:
            self._warned_legacy_api_urls.add(model_config.api_url)
            logger.warning(
                "[配置弃用] 检测到 *_MODEL_API_URL 末尾包含 /chat/completions，这种写法已弃用；"
                "已自动裁剪为 base_url=%s（原值=%s）。",
                base_url,
                model_config.api_url,
            )

        client = self._get_openai_client(
            base_url=base_url, api_key=model_config.api_key, default_query=default_query
        )
        params, extra_body = _split_chat_completion_params(request_body)
        if extra_body:
            params["extra_body"] = extra_body
        response = await client.chat.completions.create(**params)
        return self._response_to_dict(response)

    def _get_openai_client(
        self, base_url: str, api_key: str, default_query: dict[str, object] | None
    ) -> AsyncOpenAI:
        query_key = None
        if default_query:
            query_key = tuple(
                sorted((str(k), str(v)) for k, v in default_query.items())
            )
        cache_key = (base_url, api_key, query_key)
        client = self._openai_clients.get(cache_key)
        if client is not None:
            return client
        # 复用上层注入的 httpx client（连接池/超时等），避免每个 OpenAI client 自建连接池。
        client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=120.0,
            default_query=default_query,
            http_client=self._http_client,
        )
        self._openai_clients[cache_key] = client
        return client

    def _response_to_dict(self, response: Any) -> dict[str, Any]:
        if isinstance(response, dict):
            return response
        for attr in ("model_dump", "to_dict", "dict"):
            method = getattr(response, attr, None)
            if callable(method):
                try:
                    value = method()
                    if isinstance(value, dict):
                        return value
                except Exception:
                    continue
        to_json = getattr(response, "to_json", None)
        if callable(to_json):
            try:
                raw_json = to_json()
                loaded = json.loads(str(raw_json))
                if isinstance(loaded, dict):
                    return loaded
            except Exception:
                pass
        return {"data": str(response)}

    def _normalize_result(self, result: dict[str, Any]) -> dict[str, Any]:
        choices = result.get("choices")
        if isinstance(choices, list):
            return result
        data = result.get("data")
        if isinstance(data, dict):
            data_choices = data.get("choices")
            if isinstance(data_choices, list):
                normalized = dict(result)
                normalized["choices"] = data_choices
                return normalized
        normalized = dict(result)
        normalized["choices"] = [{}]
        return normalized

    def _get_token_counter(self, model_name: str) -> TokenCounter:
        counter = self._token_counters.get(model_name)
        if counter is None:
            counter = TokenCounter(model_name)
            self._token_counters[model_name] = counter
        return counter

    def _estimate_usage(
        self,
        model_name: str,
        messages: list[dict[str, Any]],
        result: dict[str, Any],
    ) -> tuple[int, int, int]:
        counter = self._get_token_counter(model_name)
        try:
            prompt_text = "\n".join(
                json.dumps(message, ensure_ascii=False, default=str)
                for message in messages
            )
        except Exception:
            prompt_text = str(messages)
        prompt_tokens = counter.count(prompt_text)

        completion_text = ""
        try:
            completion_text = extract_choices_content(result)
        except Exception:
            completion_text = ""
        if not completion_text:
            choices = result.get("choices")
            if isinstance(choices, list) and choices:
                choice = choices[0]
                if isinstance(choice, dict):
                    message = choice.get("message", {})
                    tool_calls = (
                        message.get("tool_calls")
                        if isinstance(message, dict)
                        else choice.get("tool_calls")
                    )
                    if tool_calls:
                        try:
                            completion_text = json.dumps(
                                tool_calls, ensure_ascii=False, default=str
                            )
                        except Exception:
                            completion_text = str(tool_calls)
        completion_tokens = counter.count(completion_text) if completion_text else 0
        total_tokens = prompt_tokens + completion_tokens
        logger.debug(
            "[API响应] usage 缺失，估算 tokens: prompt=%s completion=%s total=%s",
            prompt_tokens,
            completion_tokens,
            total_tokens,
        )
        return prompt_tokens, completion_tokens, total_tokens


def build_request_body(
    model_config: ModelConfig,
    messages: list[dict[str, Any]],
    max_tokens: int,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: str = "auto",
    **kwargs: Any,
) -> dict[str, Any]:
    """构建 API 请求体。"""
    body: dict[str, Any] = {
        "model": model_config.model_name,
        "messages": messages,
        "max_tokens": max_tokens,
    }

    extra_kwargs: dict[str, Any] = dict(kwargs)
    if "thinking" in extra_kwargs:
        normalized = _normalize_thinking_override(
            extra_kwargs.get("thinking"), model_config
        )
        if normalized is None:
            extra_kwargs.pop("thinking", None)
        else:
            extra_kwargs["thinking"] = normalized

    if model_config.thinking_enabled:
        if getattr(model_config, "deepseek_new_cot_support", False):
            # DeepSeek thinking mode 只需要 {"type":"enabled"}；额外字段可能导致兼容性问题。
            body["thinking"] = {"type": "enabled"}
        else:
            body["thinking"] = {
                "type": "enabled",
                "budget_tokens": model_config.thinking_budget_tokens,
            }

    if tools:
        body["tools"] = tools
        body["tool_choice"] = tool_choice

    body.update(extra_kwargs)
    return body
