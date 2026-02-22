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


async def execute(args: dict[str, Any], context: dict[str, Any]) -> str:
    km = context.get("knowledge_manager")
    if km is None:
        return "知识库功能未启用"

    raw_intro_max_chars = args.get("intro_max_chars")
    intro_max_chars = 300
    if raw_intro_max_chars is not None:
        try:
            intro_max_chars = int(raw_intro_max_chars)
        except (TypeError, ValueError):
            return "错误：intro_max_chars 必须是整数"
        if intro_max_chars <= 0:
            return "错误：intro_max_chars 必须大于 0"

    only_ready = _parse_bool(args.get("only_ready"), default=True)
    infos = km.list_knowledge_base_infos(
        intro_max_chars=intro_max_chars,
        only_ready=only_ready,
    )
    return json.dumps(infos, ensure_ascii=False, indent=2)
