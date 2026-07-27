"""Tool call helpers."""

from __future__ import annotations

import json
import logging
import re
from html import unescape
from typing import Any
from uuid import uuid4

from Undefined.utils.logging import format_log_payload

logger = logging.getLogger(__name__)

_CODE_FENCE_PREFIXES: tuple[str, ...] = ("```json", "```JSON", "```")

_JSON_DUMPS_KWARGS: dict[str, Any] = {
    "ensure_ascii": False,
    "separators": (",", ":"),
    "default": str,
}

_JSON_TOOL_CALLS_MARKER_RE = re.compile(r'"tool_calls"\s*:', re.DOTALL)
_JSON_TOOL_MARKER_RE = re.compile(r'\{\s*"tool"\s*:', re.DOTALL)
_JSON_NAME_MARKER_RE = re.compile(r'\{\s*"name"\s*:', re.DOTALL)
_JSON_ARGUMENTS_MARKER_RE = re.compile(r'"arguments"\s*:', re.DOTALL)
_TOOL_TAG_PREFIX_RE = re.compile(r"^<tool(?:\s|/?>)", re.IGNORECASE)
_TOOL_TAG_MARKER_RE = re.compile(r"<tool(?:\s|/?>)", re.IGNORECASE)
_TOOL_EXECUTION_PREFIX_RE = re.compile(r"^<tool_execution(?:\s|>)", re.IGNORECASE)
_TOOL_EXECUTION_MARKER_RE = re.compile(
    r"<(?:tool_execution|tool_call)(?:\s|/?>)", re.IGNORECASE
)
_TOOL_CALL_PREFIX_RE = re.compile(r"^<tool_call(?:\s|/?>)", re.IGNORECASE)
_FUNCTION_CALLS_PREFIX_RE = re.compile(r"^<function_calls(?:\s|>)", re.IGNORECASE)
_FUNCTION_CALLS_MARKER_RE = re.compile(
    r"<(?:function_calls|invoke)(?:\s|/?>)", re.IGNORECASE
)
_INVOKE_PREFIX_RE = re.compile(r"^<invoke(?:\s|/?>)", re.IGNORECASE)
_FUNCTION_EQUALS_PREFIX_RE = re.compile(r"^<function\s*=", re.IGNORECASE)
_FUNCTION_EQUALS_MARKER_RE = re.compile(r"<(?:function|parameter)\s*=", re.IGNORECASE)
_PARAMETER_EQUALS_PREFIX_RE = re.compile(r"^<parameter\s*=", re.IGNORECASE)
_TOOL_ATTRIBUTE_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_.:-]*")
_TOOL_CALLS_ENVELOPE_KEYS = frozenset({"tool_calls"})
_TOOL_ENVELOPE_KEYS = frozenset({"tool", "arguments"})
_NAMED_TOOL_ENVELOPE_KEYS = frozenset({"name", "arguments"})
_TOOL_CALLS_ITEM_KEYS = frozenset({"id", "name", "arguments"})
_TOOL_TAG_ATTRIBUTE_KEYS = frozenset({"name", "params", "parameters", "arguments"})
_TOOL_TAG_ARGUMENT_KEYS = ("params", "parameters", "arguments")
_TOOL_CALL_ATTRIBUTE_KEYS = frozenset({"name", "arguments"})
_INVOKE_ATTRIBUTE_KEYS = frozenset({"name"})


class TextToolCallParseError(ValueError):
    """模型文本看似工具封包，但不能安全转换为标准工具调用。"""


def _skip_whitespace(text: str, position: int) -> int:
    while position < len(text) and text[position].isspace():
        position += 1
    return position


def _parse_text_tool_arguments(raw_arguments: Any) -> dict[str, Any]:
    if raw_arguments is None:
        return {}
    if isinstance(raw_arguments, dict):
        return dict(raw_arguments)
    if isinstance(raw_arguments, str):
        try:
            parsed = json.loads(raw_arguments)
        except json.JSONDecodeError as exc:
            raise TextToolCallParseError("工具参数不是有效 JSON 对象") from exc
        if isinstance(parsed, dict):
            return parsed
    raise TextToolCallParseError("工具参数必须是 JSON 对象")


def _build_text_tool_call(
    name: Any,
    raw_arguments: Any,
    *,
    call_id: str | None = None,
) -> dict[str, Any]:
    if not isinstance(name, str) or not name.strip():
        raise TextToolCallParseError("工具名称必须是非空字符串")
    arguments = _parse_text_tool_arguments(raw_arguments)
    return {
        "id": call_id or f"call_txt_{uuid4().hex[:24]}",
        "type": "function",
        "function": {
            "name": name.strip(),
            "arguments": json.dumps(arguments, **_JSON_DUMPS_KWARGS),
        },
    }


def _tool_call_from_json_envelope(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TextToolCallParseError("连续 JSON 中包含非工具封包")
    if "tool" in value:
        unexpected_keys = set(value) - _TOOL_ENVELOPE_KEYS
        if unexpected_keys:
            raise TextToolCallParseError("JSON 工具封包含有不支持的字段")
        return _build_text_tool_call(value.get("tool"), value.get("arguments", {}))
    if "name" in value and "arguments" in value:
        unexpected_keys = set(value) - _NAMED_TOOL_ENVELOPE_KEYS
        if unexpected_keys:
            raise TextToolCallParseError("JSON 工具封包含有不支持的字段")
        return _build_text_tool_call(value.get("name"), value.get("arguments"))
    raise TextToolCallParseError("连续 JSON 中包含非工具封包")


def _is_json_tool_envelope(value: Any) -> bool:
    return isinstance(value, dict) and (
        "tool" in value or ("name" in value and "arguments" in value)
    )


def _is_json_tool_calls_envelope(value: Any) -> bool:
    return isinstance(value, dict) and "tool_calls" in value


def _tool_calls_from_json_envelope(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, dict):
        raise TextToolCallParseError("tool_calls JSON 封包必须是对象")
    unexpected_keys = set(value) - _TOOL_CALLS_ENVELOPE_KEYS
    if unexpected_keys:
        raise TextToolCallParseError("tool_calls JSON 封包含有不支持的字段")

    raw_tool_calls = value.get("tool_calls")
    if not isinstance(raw_tool_calls, list):
        raise TextToolCallParseError("tool_calls 字段必须是数组")
    if not raw_tool_calls:
        raise TextToolCallParseError("tool_calls 数组不能为空")

    tool_calls: list[dict[str, Any]] = []
    seen_call_ids: set[str] = set()
    for raw_tool_call in raw_tool_calls:
        if not isinstance(raw_tool_call, dict):
            raise TextToolCallParseError("tool_calls 数组包含非对象调用")
        raw_keys = set(raw_tool_call)
        if not _NAMED_TOOL_ENVELOPE_KEYS.issubset(raw_keys) or (
            raw_keys - _TOOL_CALLS_ITEM_KEYS
        ):
            raise TextToolCallParseError(
                "tool_calls 数组项必须包含 name 与 arguments，且只允许额外提供 id"
            )

        call_id: str | None = None
        if "id" in raw_tool_call:
            raw_call_id = raw_tool_call.get("id")
            if (
                not isinstance(raw_call_id, str)
                or not raw_call_id
                or raw_call_id != raw_call_id.strip()
            ):
                raise TextToolCallParseError(
                    "tool_calls 数组项的 id 必须是无首尾空白的非空字符串"
                )
            call_id = raw_call_id

        tool_call = _build_text_tool_call(
            raw_tool_call.get("name"),
            raw_tool_call.get("arguments"),
            call_id=call_id,
        )
        resolved_call_id = str(tool_call["id"])
        if resolved_call_id in seen_call_ids:
            raise TextToolCallParseError("tool_calls 数组项包含重复 id")
        seen_call_ids.add(resolved_call_id)
        tool_calls.append(tool_call)
    return tool_calls


def _has_json_tool_marker(text: str) -> bool:
    return bool(
        _JSON_TOOL_CALLS_MARKER_RE.search(text)
        or _JSON_TOOL_MARKER_RE.search(text)
        or (
            _JSON_NAME_MARKER_RE.search(text) and _JSON_ARGUMENTS_MARKER_RE.search(text)
        )
    )


def _parse_json_text_tool_calls(text: str) -> list[dict[str, Any]]:
    decoder = json.JSONDecoder()
    position = 0
    values: list[Any] = []

    while True:
        position = _skip_whitespace(text, position)
        if position >= len(text):
            break
        try:
            value, position = decoder.raw_decode(text, position)
        except json.JSONDecodeError as exc:
            has_tool_envelope = any(
                _is_json_tool_envelope(item) or _is_json_tool_calls_envelope(item)
                for item in values
            )
            if has_tool_envelope or _has_json_tool_marker(text):
                raise TextToolCallParseError(
                    "JSON 工具封包后存在无法解析的内容"
                ) from exc
            return []
        values.append(value)

    wrapped_values = [value for value in values if _is_json_tool_calls_envelope(value)]
    if wrapped_values:
        if len(values) != 1:
            raise TextToolCallParseError("tool_calls JSON 封包必须单独出现")
        return _tool_calls_from_json_envelope(wrapped_values[0])
    if not any(_is_json_tool_envelope(value) for value in values):
        return []
    return [_tool_call_from_json_envelope(value) for value in values]


def _unescape_tool_attribute(raw_value: str, quote: str) -> str:
    result: list[str] = []
    position = 0
    while position < len(raw_value):
        current = raw_value[position]
        if (
            current == "\\"
            and position + 1 < len(raw_value)
            and raw_value[position + 1] in {quote, "\\"}
        ):
            result.append(raw_value[position + 1])
            position += 2
            continue
        result.append(current)
        position += 1
    return unescape("".join(result))


def _parse_attributed_tag_open(
    text: str,
    position: int,
    *,
    tag_name: str,
) -> tuple[dict[str, str], bool, int]:
    tag_prefix = f"<{tag_name}"
    if text[position : position + len(tag_prefix)].lower() != tag_prefix:
        raise TextToolCallParseError("工具标签开头无效")
    position += len(tag_prefix)
    if position >= len(text) or not text[position].isspace():
        raise TextToolCallParseError("工具标签缺少属性")

    attributes: dict[str, str] = {}
    while True:
        position = _skip_whitespace(text, position)
        if text.startswith("/>", position):
            return attributes, True, position + 2
        if position < len(text) and text[position] == ">":
            return attributes, False, position + 1

        matched = _TOOL_ATTRIBUTE_NAME_RE.match(text, position)
        if matched is None:
            raise TextToolCallParseError("工具标签属性名称无效")
        attribute_name = matched.group(0).lower()
        if attribute_name in attributes:
            raise TextToolCallParseError("工具标签包含重复属性")
        position = _skip_whitespace(text, matched.end())
        if position >= len(text) or text[position] != "=":
            raise TextToolCallParseError("工具标签属性缺少等号")
        position = _skip_whitespace(text, position + 1)
        if position >= len(text) or text[position] not in {"'", '"'}:
            raise TextToolCallParseError("工具标签属性必须使用引号")

        quote = text[position]
        position += 1
        value_parts: list[str] = []
        while position < len(text):
            current = text[position]
            if current == quote:
                position += 1
                break
            if current == "\\" and position + 1 < len(text):
                value_parts.extend((current, text[position + 1]))
                position += 2
                continue
            value_parts.append(current)
            position += 1
        else:
            raise TextToolCallParseError("工具标签属性缺少结束引号")

        attributes[attribute_name] = _unescape_tool_attribute(
            "".join(value_parts), quote
        )


def _parse_tool_tag_open(text: str, position: int) -> tuple[dict[str, str], bool, int]:
    return _parse_attributed_tag_open(text, position, tag_name="tool")


def _tool_call_from_tag_attributes(attributes: dict[str, str]) -> dict[str, Any]:
    unexpected_keys = set(attributes) - _TOOL_TAG_ATTRIBUTE_KEYS
    if unexpected_keys:
        raise TextToolCallParseError("工具标签含有不支持的属性")
    argument_keys = [key for key in _TOOL_TAG_ARGUMENT_KEYS if key in attributes]
    if len(argument_keys) > 1:
        raise TextToolCallParseError("工具标签包含多个参数属性")
    raw_arguments = attributes[argument_keys[0]] if argument_keys else {}
    return _build_text_tool_call(attributes.get("name"), raw_arguments)


def _parse_tag_text_tool_calls(text: str) -> list[dict[str, Any]]:
    position = 0
    tool_calls: list[dict[str, Any]] = []
    while True:
        position = _skip_whitespace(text, position)
        if position >= len(text):
            return tool_calls
        if _TOOL_TAG_PREFIX_RE.match(text[position:]) is None:
            raise TextToolCallParseError("工具标签之间存在普通文本")

        attributes, self_closing, position = _parse_tool_tag_open(text, position)
        tool_calls.append(_tool_call_from_tag_attributes(attributes))
        if self_closing:
            continue

        position = _skip_whitespace(text, position)
        if text[position : position + 7].lower() != "</tool>":
            raise TextToolCallParseError("工具标签只允许空内容")
        position += 7


def _parse_unattributed_tag_open(
    text: str,
    position: int,
    *,
    tag_name: str,
) -> int:
    tag_prefix = f"<{tag_name}"
    if text[position : position + len(tag_prefix)].lower() != tag_prefix:
        raise TextToolCallParseError(f"{tag_name} 标签开头无效")
    position = _skip_whitespace(text, position + len(tag_prefix))
    if position >= len(text) or text[position] != ">":
        raise TextToolCallParseError(f"{tag_name} 标签不允许属性或自闭合")
    return position + 1


def _parse_tool_execution_open(text: str, position: int) -> int:
    return _parse_unattributed_tag_open(
        text,
        position,
        tag_name="tool_execution",
    )


def _tool_call_from_execution_attributes(
    attributes: dict[str, str],
) -> dict[str, Any]:
    unexpected_keys = set(attributes) - _TOOL_CALL_ATTRIBUTE_KEYS
    if unexpected_keys:
        raise TextToolCallParseError("tool_call 标签含有不支持的属性")
    return _build_text_tool_call(
        attributes.get("name"),
        attributes.get("arguments", {}),
    )


def _parse_tool_execution_text_tool_calls(text: str) -> list[dict[str, Any]]:
    position = _parse_tool_execution_open(text, 0)
    tool_calls: list[dict[str, Any]] = []

    while True:
        position = _skip_whitespace(text, position)
        if text[position : position + 17].lower() == "</tool_execution>":
            position = _skip_whitespace(text, position + 17)
            if position != len(text):
                raise TextToolCallParseError("tool_execution 标签后存在普通文本")
            if not tool_calls:
                raise TextToolCallParseError("tool_execution 封包不能为空")
            return tool_calls
        if position >= len(text) or _TOOL_CALL_PREFIX_RE.match(text[position:]) is None:
            raise TextToolCallParseError("tool_execution 内只允许 tool_call 标签")

        attributes, self_closing, position = _parse_attributed_tag_open(
            text,
            position,
            tag_name="tool_call",
        )
        tool_calls.append(_tool_call_from_execution_attributes(attributes))
        if self_closing:
            continue

        position = _skip_whitespace(text, position)
        if text[position : position + 12].lower() != "</tool_call>":
            raise TextToolCallParseError("tool_call 标签只允许空内容")
        position += 12


def _parse_function_calls_text_tool_calls(text: str) -> list[dict[str, Any]]:
    position = _parse_unattributed_tag_open(
        text,
        0,
        tag_name="function_calls",
    )
    lowered_text = text.lower()
    tool_calls: list[dict[str, Any]] = []

    while True:
        position = _skip_whitespace(text, position)
        if lowered_text.startswith("</function_calls>", position):
            position = _skip_whitespace(text, position + len("</function_calls>"))
            if position != len(text):
                raise TextToolCallParseError("function_calls 标签后存在普通文本")
            if not tool_calls:
                raise TextToolCallParseError("function_calls 封包不能为空")
            return tool_calls
        if position >= len(text) or _INVOKE_PREFIX_RE.match(text[position:]) is None:
            raise TextToolCallParseError("function_calls 内只允许 invoke 标签")

        attributes, self_closing, position = _parse_attributed_tag_open(
            text,
            position,
            tag_name="invoke",
        )
        if self_closing:
            raise TextToolCallParseError("invoke 标签不允许自闭合")
        unexpected_keys = set(attributes) - _INVOKE_ATTRIBUTE_KEYS
        if unexpected_keys:
            raise TextToolCallParseError("invoke 标签含有不支持的属性")

        position = _skip_whitespace(text, position)
        arguments_start = _parse_unattributed_tag_open(
            text,
            position,
            tag_name="arguments",
        )
        try:
            raw_arguments, arguments_end = json.JSONDecoder().raw_decode(
                text,
                _skip_whitespace(text, arguments_start),
            )
        except json.JSONDecodeError as exc:
            raise TextToolCallParseError("arguments 内容不是有效 JSON 对象") from exc
        position = _skip_whitespace(text, arguments_end)
        if not lowered_text.startswith("</arguments>", position):
            raise TextToolCallParseError("arguments 标签缺少结束标签")
        position = _skip_whitespace(text, position + len("</arguments>"))
        if not lowered_text.startswith("</invoke>", position):
            raise TextToolCallParseError("invoke 标签缺少结束标签")
        position += len("</invoke>")
        tool_calls.append(_build_text_tool_call(attributes.get("name"), raw_arguments))


def _parse_equals_tag_open(
    text: str,
    position: int,
    *,
    tag_name: str,
) -> tuple[str, int]:
    tag_prefix = f"<{tag_name}"
    if text[position : position + len(tag_prefix)].lower() != tag_prefix:
        raise TextToolCallParseError(f"{tag_name} 标签开头无效")
    position = _skip_whitespace(text, position + len(tag_prefix))
    if position >= len(text) or text[position] != "=":
        raise TextToolCallParseError(f"{tag_name} 标签缺少等号")
    position = _skip_whitespace(text, position + 1)

    matched = _TOOL_ATTRIBUTE_NAME_RE.match(text, position)
    if matched is None:
        raise TextToolCallParseError(f"{tag_name} 标签名称无效")
    value = matched.group(0)
    position = _skip_whitespace(text, matched.end())
    if position >= len(text) or text[position] != ">":
        raise TextToolCallParseError(f"{tag_name} 标签名称后存在不支持的内容")
    return value, position + 1


def _parse_parameter_text_value(raw_value: str) -> Any:
    value = raw_value.strip()
    if not value:
        return ""
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        if value[0] in {'"', "[", "{"}:
            raise TextToolCallParseError("parameter 内容包含无效 JSON") from exc
        return value


def _parse_function_parameter(
    text: str,
    lowered_text: str,
    position: int,
) -> tuple[str, Any, int]:
    parameter_name, content_start = _parse_equals_tag_open(
        text,
        position,
        tag_name="parameter",
    )
    closing_tag = "</parameter>"
    value_start = _skip_whitespace(text, content_start)
    if value_start < len(text) and text[value_start] in {'"', "[", "{"}:
        try:
            parameter_value, value_end = json.JSONDecoder().raw_decode(
                text,
                value_start,
            )
        except json.JSONDecodeError as exc:
            raise TextToolCallParseError("parameter 内容包含无效 JSON") from exc
        closing_position = _skip_whitespace(text, value_end)
        if not lowered_text.startswith(closing_tag, closing_position):
            raise TextToolCallParseError("parameter JSON 后存在不支持的内容")
        return (
            parameter_name,
            parameter_value,
            closing_position + len(closing_tag),
        )

    closing_position = lowered_text.find(closing_tag, content_start)
    if closing_position < 0:
        raise TextToolCallParseError("parameter 标签缺少结束标签")
    raw_value = text[content_start:closing_position]
    return (
        parameter_name,
        _parse_parameter_text_value(raw_value),
        closing_position + len(closing_tag),
    )


def _parse_function_equals_text_tool_calls(text: str) -> list[dict[str, Any]]:
    position = 0
    lowered_text = text.lower()
    tool_calls: list[dict[str, Any]] = []

    while True:
        position = _skip_whitespace(text, position)
        if position >= len(text):
            if not tool_calls:
                raise TextToolCallParseError("function 封包不能为空")
            return tool_calls
        if _FUNCTION_EQUALS_PREFIX_RE.match(text[position:]) is None:
            raise TextToolCallParseError("function 工具封包之间存在普通文本")

        function_name, position = _parse_equals_tag_open(
            text,
            position,
            tag_name="function",
        )
        parameters: dict[str, Any] = {}
        while True:
            position = _skip_whitespace(text, position)
            if lowered_text.startswith("</function>", position):
                position += len("</function>")
                tool_calls.append(_build_text_tool_call(function_name, parameters))
                break
            if (
                position >= len(text)
                or _PARAMETER_EQUALS_PREFIX_RE.match(text[position:]) is None
            ):
                raise TextToolCallParseError("function 标签内只允许 parameter 标签")
            parameter_name, parameter_value, position = _parse_function_parameter(
                text,
                lowered_text,
                position,
            )
            if parameter_name in parameters:
                raise TextToolCallParseError("function 标签包含重复 parameter")
            parameters[parameter_name] = parameter_value


def parse_text_tool_calls(raw_content: str) -> list[dict[str, Any]]:
    """将完整的模型文本工具封包转换为 OpenAI ``tool_calls``。

    普通文本返回空列表。疑似工具协议但格式非法时抛出
    :class:`TextToolCallParseError`，由调用方决定是否按普通文本重试。
    """

    text = _strip_code_fences(raw_content).strip()
    if not text:
        return []
    if _FUNCTION_EQUALS_PREFIX_RE.match(text):
        return _parse_function_equals_text_tool_calls(text)
    if _FUNCTION_EQUALS_MARKER_RE.search(text):
        raise TextToolCallParseError("function 工具封包前存在普通文本")
    if _FUNCTION_CALLS_PREFIX_RE.match(text):
        return _parse_function_calls_text_tool_calls(text)
    if _FUNCTION_CALLS_MARKER_RE.search(text):
        raise TextToolCallParseError("function_calls 工具封包前存在普通文本")
    if _TOOL_EXECUTION_PREFIX_RE.match(text):
        return _parse_tool_execution_text_tool_calls(text)
    if _TOOL_EXECUTION_MARKER_RE.search(text):
        raise TextToolCallParseError("tool_execution 工具封包前存在普通文本")
    if _TOOL_TAG_PREFIX_RE.match(text):
        return _parse_tag_text_tool_calls(text)
    if _TOOL_TAG_MARKER_RE.search(text):
        raise TextToolCallParseError("工具标签前存在普通文本")
    return _parse_json_text_tool_calls(text)


def _clean_json_string(raw: str) -> str:
    """Remove control characters that commonly break JSON parsing."""
    return raw.replace("\r", " ").replace("\n", " ").replace("\t", " ").strip()


def _strip_code_fences(raw: str) -> str:
    """Strip common markdown code fences from tool arguments."""
    text = raw.strip()
    for prefix in _CODE_FENCE_PREFIXES:
        if text.startswith(prefix):
            # Remove first line fence
            parts = text.splitlines()
            if len(parts) >= 2:
                text = "\n".join(parts[1:])
            break
    if text.endswith("```"):
        text = text[: -len("```")]
    return text.strip()


def _repair_json_like_string(raw: str) -> str:
    """Best-effort repair for truncated JSON-like strings.

    Common failure mode for tool arguments is a missing trailing '}' / ']' or a
    dangling comma. We try to repair these in a conservative way.
    """
    text = _strip_code_fences(raw)
    text = text.strip()
    if not text:
        return text

    # Remove trailing commas/spaces
    while text and text[-1] in {",", " "}:
        text = text[:-1].rstrip()

    # Balance brackets/braces (append missing closers only).
    opens = text.count("{") - text.count("}")
    if opens > 0:
        text = text + ("}" * opens)

    opens_sq = text.count("[") - text.count("]")
    if opens_sq > 0:
        text = text + ("]" * opens_sq)

    return text


def parse_tool_arguments(
    raw_args: Any,
    *,
    logger: logging.Logger | None = None,
    tool_name: str | None = None,
) -> dict[str, Any]:
    """Parse tool call arguments into a dict.

    Accepts dict, JSON string, or empty/None. Returns an empty dict for
    unsupported or invalid inputs.
    """
    if isinstance(raw_args, dict):
        return raw_args

    if raw_args is None:
        return {}

    if isinstance(raw_args, str):
        if not raw_args.strip():
            return {}
        cleaned = _strip_code_fences(raw_args)
        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            cleaned2 = _clean_json_string(cleaned)
            if cleaned2 != cleaned:
                try:
                    parsed = json.loads(cleaned2)
                    if logger:
                        logger.warning(
                            "[工具警告] 参数包含控制字符，已清理: tool=%s",
                            tool_name or "unknown",
                        )
                    return parsed if isinstance(parsed, dict) else {}
                except json.JSONDecodeError:
                    pass
            cleaned = cleaned2
            # Repair common truncated JSON (missing closing braces/brackets, dangling comma).
            repaired = _repair_json_like_string(cleaned)
            if repaired and repaired != cleaned:
                try:
                    parsed = json.loads(repaired)
                    if logger:
                        logger.warning(
                            "[工具警告] 参数 JSON 不完整，已自动修复: tool=%s raw_call=%s repaired_call=%s",
                            tool_name or "unknown",
                            format_log_payload(raw_args, max_length=2000),
                            format_log_payload(repaired, max_length=2000),
                        )
                    return parsed if isinstance(parsed, dict) else {}
                except json.JSONDecodeError:
                    pass
            try:
                parsed, _ = json.JSONDecoder().raw_decode(cleaned)
                if logger:
                    logger.warning(
                        "[工具警告] 参数包含尾部内容，已截断: tool=%s",
                        tool_name or "unknown",
                    )
                return parsed if isinstance(parsed, dict) else {}
            except json.JSONDecodeError:
                if logger:
                    logger.error(
                        "[工具错误] 参数解析失败: %s, 错误: %s",
                        raw_args,
                        exc,
                    )
                return {}
        if isinstance(parsed, dict):
            return parsed
        if logger:
            logger.warning(
                "[工具警告] 参数解析结果非对象: tool=%s type=%s",
                tool_name or "unknown",
                type(parsed).__name__,
            )
        return {}

    if logger:
        logger.warning(
            "[工具警告] 参数类型不支持: tool=%s type=%s",
            tool_name or "unknown",
            type(raw_args).__name__,
        )
    return {}


def normalize_tool_arguments_json(raw_args: Any) -> str:
    """Normalize tool call `function.arguments` to a strict JSON object string.

    Some OpenAI-compatible providers validate that assistant/tool_calls/function.arguments
    is valid JSON (and often expect an object). When models emit non-JSON or when
    callers accidentally store a dict, subsequent requests can fail with 400.

    This function always returns a JSON object string:
    - dict -> JSON object string
    - JSON string -> re-dumped JSON object (or wrapped into {"_value": ...})
    - invalid / empty string -> {"_raw": "..."} or {}
    - other types -> {"_value": ...}
    """
    if raw_args is None:
        return "{}"

    if isinstance(raw_args, dict):
        return json.dumps(raw_args, **_JSON_DUMPS_KWARGS)

    if isinstance(raw_args, str):
        raw_text = raw_args
        if not raw_text.strip():
            return "{}"

        cleaned = _strip_code_fences(raw_text)
        candidates = [cleaned]
        cleaned2 = _clean_json_string(cleaned)
        if cleaned2 != cleaned:
            candidates.append(cleaned2)
        repaired = _repair_json_like_string(cleaned2)
        if repaired and repaired not in candidates:
            candidates.append(repaired)

        parsed_any: Any | None = None
        for candidate in candidates:
            try:
                parsed_any = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed_any, dict):
                return json.dumps(parsed_any, **_JSON_DUMPS_KWARGS)
            break

        if parsed_any is not None:
            return json.dumps({"_value": parsed_any}, **_JSON_DUMPS_KWARGS)

        return json.dumps({"_raw": raw_text}, **_JSON_DUMPS_KWARGS)

    return json.dumps({"_value": raw_args}, **_JSON_DUMPS_KWARGS)


def extract_required_tool_call_arguments(
    response: dict[str, Any],
    *,
    expected_tool_name: str,
    stage: str,
    logger: logging.Logger | None = None,
    error_context: str = "",
) -> dict[str, Any]:
    """Extract arguments from the first required tool call in a model response."""
    context_suffix = f" {error_context}" if error_context else ""
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        if logger:
            logger.error("[工具错误] %s 响应缺少 choices%s", stage, context_suffix)
        raise ValueError(f"{stage} 响应缺少 choices{context_suffix}")

    choice = choices[0]
    if not isinstance(choice, dict):
        if logger:
            logger.error("[工具错误] %s choice 类型非法%s", stage, context_suffix)
        raise ValueError(f"{stage} choice 类型非法{context_suffix}")

    message = choice.get("message")
    if not isinstance(message, dict):
        if logger:
            logger.error("[工具错误] %s 响应缺少 message%s", stage, context_suffix)
        raise ValueError(f"{stage} 响应缺少 message{context_suffix}")

    tool_calls = message.get("tool_calls")
    if not isinstance(tool_calls, list) or not tool_calls:
        if logger:
            logger.error(
                "[工具错误] %s 响应缺少 tool_calls%s content_preview=%s",
                stage,
                context_suffix,
                format_log_payload(str(message.get("content", "")), max_length=200),
            )
        raise ValueError(f"{stage} 响应缺少 tool_calls{context_suffix}")

    tool_call = tool_calls[0]
    if not isinstance(tool_call, dict):
        if logger:
            logger.error("[工具错误] %s tool_call 类型非法%s", stage, context_suffix)
        raise ValueError(f"{stage} tool_call 类型非法{context_suffix}")

    function = tool_call.get("function")
    if not isinstance(function, dict):
        if logger:
            logger.error("[工具错误] %s function 缺失%s", stage, context_suffix)
        raise ValueError(f"{stage} function 缺失{context_suffix}")

    tool_name = str(function.get("name", "")).strip()
    if tool_name != expected_tool_name:
        if logger:
            logger.error(
                "[工具错误] %s 工具名不匹配%s expected=%s actual=%s",
                stage,
                context_suffix,
                expected_tool_name,
                tool_name,
            )
        raise ValueError(f"{stage} 工具名不匹配{context_suffix}: {tool_name}")

    parsed = parse_tool_arguments(
        function.get("arguments"),
        logger=logger,
        tool_name=expected_tool_name,
    )
    if not isinstance(parsed, dict):
        if logger:
            logger.error("[工具错误] %s 工具参数类型非法", stage)
        raise ValueError(f"{stage} 工具参数类型非法")
    return parsed
