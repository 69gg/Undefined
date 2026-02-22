from __future__ import annotations
import asyncio
from pathlib import Path
from typing import Any
import json


def _parse_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "on"}:
            return True
        if lowered in {"false", "0", "no", "off"}:
            return False
    return default


def _parse_int(
    value: Any,
    *,
    default: int,
    min_value: int,
    max_value: int,
) -> int:
    if value is None:
        return default
    parsed = int(value)
    if parsed < min_value or parsed > max_value:
        raise ValueError
    return parsed


def _trim_text(text: str, max_chars: int) -> str:
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    return f"{text[: max_chars - 1].rstrip()}…"


def _is_valid_kb_name(value: str) -> bool:
    stripped = value.strip()
    if not stripped:
        return False
    kb_path = Path(stripped)
    return (
        not kb_path.is_absolute()
        and len(kb_path.parts) == 1
        and kb_path.parts[0] not in {".", ".."}
    )


async def execute(args: dict[str, Any], context: dict[str, Any]) -> str:
    km = context.get("knowledge_manager")
    if km is None:
        return "知识库功能未启用"
    kb = str(args.get("knowledge_base", "")).strip()
    keyword = str(args.get("keyword", "")).strip()
    if not kb or not keyword:
        return "错误：knowledge_base 和 keyword 不能为空"
    if not _is_valid_kb_name(kb):
        return "错误：knowledge_base 格式非法"

    try:
        max_lines = _parse_int(
            args.get("max_lines"), default=20, min_value=1, max_value=500
        )
        max_chars = _parse_int(
            args.get("max_chars"), default=2000, min_value=100, max_value=20000
        )
        max_chars_per_item = _parse_int(
            args.get("max_chars_per_item"),
            default=180,
            min_value=20,
            max_value=5000,
        )
    except (TypeError, ValueError):
        return "错误：max_lines / max_chars / max_chars_per_item 参数不合法"

    case_sensitive = _parse_bool(args.get("case_sensitive"), default=False)
    include_line = _parse_bool(args.get("include_line"), default=True)
    include_source = _parse_bool(args.get("include_source"), default=True)
    source_keyword = str(args.get("source_keyword") or "").strip()

    results = await asyncio.to_thread(
        km.text_search,
        kb,
        keyword,
        max_lines=max_lines,
        max_chars=max_chars,
        case_sensitive=case_sensitive,
        source_keyword=source_keyword or None,
    )

    items: list[dict[str, Any]] = []
    for item in results:
        record: dict[str, Any] = {
            "text": _trim_text(str(item.get("content", "")), max_chars_per_item)
        }
        if include_source:
            record["source"] = str(item.get("source", ""))
        if include_line:
            record["line"] = int(item.get("line", 0) or 0)
        items.append(record)

    payload = {
        "ok": True,
        "knowledge_base": kb,
        "keyword": keyword,
        "count": len(items),
        "items": items,
    }
    return json.dumps(payload, ensure_ascii=False)
