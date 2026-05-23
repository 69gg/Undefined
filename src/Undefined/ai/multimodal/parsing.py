"""多模态模型响应解析工具。"""

from __future__ import annotations

import json
from typing import Any

from Undefined.utils.coerce import safe_float


def _parse_line_value(line: str, prefix: str) -> str:
    """解析行内容，提取指定前缀后的值。"""
    value = line.split("：", 1)[-1].split(":", 1)[-1].strip()
    return "" if value == "无" else value


def _parse_analysis_response(content: str) -> dict[str, str]:
    """解析 AI 分析响应的内容。"""
    field_prefixes = {
        "description": ("描述：", "描述:"),
        "ocr_text": ("OCR：", "OCR:"),
        "transcript": ("转写：", "转写:"),
        "subtitles": ("字幕：", "字幕:"),
    }

    result = {
        "description": "",
        "ocr_text": "",
        "transcript": "",
        "subtitles": "",
    }

    for line in content.split("\n"):
        line = line.strip()
        for field, prefixes in field_prefixes.items():
            if line.startswith(prefixes):
                result[field] = _parse_line_value(line, prefixes[0])

    if not result["description"]:
        result["description"] = content

    return result


def _extract_json_object(content: str) -> dict[str, Any]:
    text = str(content or "").strip()
    if not text:
        return {}
    candidates = [text]
    if "```" in text:
        parts = text.split("```")
        for part in parts:
            stripped = part.strip()
            if not stripped:
                continue
            if stripped.lower().startswith("json"):
                stripped = stripped[4:].strip()
            candidates.append(stripped)
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    # 兜底：从文本中截取首尾花括号再解析
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            parsed = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return {}
        if isinstance(parsed, dict):
            return parsed
    return {}


def _normalize_meme_tags(tags_raw: Any) -> list[str]:
    tags: list[str] = []
    if isinstance(tags_raw, list):
        seen: set[str] = set()
        for item in tags_raw:
            text = str(item or "").strip()
            lowered = text.lower()
            if not text or lowered in seen:
                continue
            seen.add(lowered)
            tags.append(text)
    return tags


def _parse_meme_analysis_response(content: str) -> dict[str, Any]:
    parsed = _extract_json_object(content)
    return {
        "is_meme": bool(parsed.get("is_meme", False)),
        "confidence": safe_float(parsed.get("confidence", 0.0), default=0.0),
        "description": str(parsed.get("description") or "").strip(),
        "tags": _normalize_meme_tags(parsed.get("tags")),
    }


__all__ = [
    "_normalize_meme_tags",
    "_parse_analysis_response",
    "_parse_meme_analysis_response",
]
