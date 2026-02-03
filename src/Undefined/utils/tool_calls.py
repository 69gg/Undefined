"""Tool call helpers."""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

_CODE_FENCE_PREFIXES: tuple[str, ...] = ("```json", "```JSON", "```")

_JSON_DUMPS_KWARGS: dict[str, Any] = {
    "ensure_ascii": False,
    "separators": (",", ":"),
    "default": str,
}


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
                            "[工具警告] 参数 JSON 不完整，已自动修复: tool=%s",
                            tool_name or "unknown",
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
