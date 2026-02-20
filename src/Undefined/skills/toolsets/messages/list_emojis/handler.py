from __future__ import annotations

from typing import Any, Dict

from Undefined.utils.qq_emoji import get_emoji_id_entries


def _normalize_limit(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 50
    if parsed <= 0:
        return 50
    return min(parsed, 200)


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    keyword_raw = args.get("keyword")
    keyword = keyword_raw.strip().lower() if isinstance(keyword_raw, str) else ""
    limit = _normalize_limit(args.get("limit"))

    entries = get_emoji_id_entries()
    if keyword:
        filtered: list[tuple[int, list[str]]] = []
        for emoji_id, aliases in entries:
            hit_aliases = [alias for alias in aliases if keyword in alias.lower()]
            if hit_aliases:
                filtered.append((emoji_id, hit_aliases))
        entries = filtered

    if not entries:
        if keyword:
            return f"没有匹配关键字 '{keyword}' 的 emoji 映射"
        return "当前没有可用 emoji 映射"

    lines: list[str] = []
    for emoji_id, aliases in entries[:limit]:
        preview = ", ".join(aliases[:8])
        if len(aliases) > 8:
            preview = f"{preview}, ..."
        lines.append(f"- {emoji_id}: {preview}")

    truncated_note = ""
    if len(entries) > limit:
        truncated_note = f"\n（已截断，仅显示前 {limit} 条，共 {len(entries)} 条）"

    return "可用 emoji 映射：\n" + "\n".join(lines) + truncated_note
