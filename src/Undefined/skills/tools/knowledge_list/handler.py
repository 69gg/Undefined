from __future__ import annotations
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
    min_value: int | None = None,
    max_value: int | None = None,
) -> int:
    if value is None:
        return default
    parsed = int(value)
    if min_value is not None and parsed < min_value:
        raise ValueError(f"必须 >= {min_value}")
    if max_value is not None and parsed > max_value:
        raise ValueError(f"必须 <= {max_value}")
    return parsed


async def execute(args: dict[str, Any], context: dict[str, Any]) -> str:
    km = context.get("knowledge_manager")
    if km is None:
        return "知识库功能未启用"

    try:
        intro_max_chars = _parse_int(
            args.get("intro_max_chars"),
            default=120,
            min_value=1,
            max_value=2000,
        )
        max_items = _parse_int(
            args.get("max_items"),
            default=50,
            min_value=1,
            max_value=500,
        )
    except (TypeError, ValueError):
        return "错误：intro_max_chars / max_items 参数不合法"

    only_ready = _parse_bool(args.get("only_ready"), default=True)
    include_intro = _parse_bool(args.get("include_intro"), default=True)
    include_has_intro = _parse_bool(args.get("include_has_intro"), default=False)
    name_keyword = str(args.get("name_keyword") or "").strip().lower()

    infos = km.list_knowledge_base_infos(
        intro_max_chars=intro_max_chars,
        only_ready=only_ready,
    )
    if name_keyword:
        infos = [
            item for item in infos if name_keyword in str(item.get("name", "")).lower()
        ]

    truncated = len(infos) > max_items
    infos = infos[:max_items]

    items: list[dict[str, Any]] = []
    for item in infos:
        record: dict[str, Any] = {"name": str(item.get("name", ""))}
        if include_intro:
            record["intro"] = str(item.get("intro", ""))
        if include_has_intro:
            record["has_intro"] = bool(item.get("has_intro", False))
        items.append(record)

    payload = {
        "ok": True,
        "count": len(items),
        "truncated": truncated,
        "items": items,
    }
    return json.dumps(payload, ensure_ascii=False)
