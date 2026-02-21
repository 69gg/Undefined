"""QQ emoji ID 映射工具。

提供能力：
- 内置常用 emoji 名称/字符到 ID 的映射
- 从本地 JSON 文件加载并覆盖映射
- 名称查询、列表输出（供工具层复用）
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_MAP_PATHS: tuple[Path, ...] = (
    Path("data/qq_emoji_map.json"),
    Path("config/qq_emoji_map.json"),
)

# 说明：这里提供的是“常用”映射，完整映射可通过 data/config 覆盖文件维护。
_DEFAULT_ALIAS_TO_ID: dict[str, int] = {
    "微笑": 14,
    "smile": 14,
    "🙂": 14,
    "呲牙": 13,
    "grin": 13,
    "😀": 13,
    "色": 2,
    "发呆": 3,
    "大哭": 9,
    "cry": 9,
    "😭": 9,
    "尴尬": 10,
    "发怒": 11,
    "angry": 11,
    "😠": 11,
    "调皮": 12,
    "😜": 12,
    "难过": 15,
    "cool": 16,
    "酷": 16,
    "抓狂": 18,
    "偷笑": 20,
    "可爱": 21,
    "白眼": 22,
    "傲慢": 23,
    "惊恐": 26,
    "流汗": 27,
    "憨笑": 28,
    "奋斗": 30,
    "疑问": 32,
    "question": 32,
    "嘘": 33,
    "晕": 34,
    "衰": 36,
    "再见": 39,
    "拥抱": 49,
    "爱心": 66,
    "heart": 66,
    "❤️": 66,
    "心碎": 67,
    "broken_heart": 67,
    "💔": 67,
    "礼物": 69,
    "太阳": 74,
    "月亮": 75,
    "赞": 76,
    "点赞": 76,
    "like": 76,
    "thumbs_up": 76,
    "👍": 76,
    "弱": 77,
    "thumbs_down": 77,
    "👎": 77,
    "握手": 78,
    "胜利": 79,
    "v": 79,
    "✌️": 79,
    "飞吻": 85,
    "冷汗": 96,
    "擦汗": 97,
    "鼓掌": 99,
    "clap": 99,
    "👏": 99,
    "坏笑": 101,
    "鄙视": 105,
    "委屈": 106,
    "阴险": 108,
    "亲亲": 109,
    "可怜": 111,
    "抱拳": 118,
    "拳头": 120,
    "差劲": 121,
    "爱你": 122,
    "ok": 124,
    "转圈": 125,
}


def _normalize_alias(alias: str) -> str:
    return alias.strip().lower()


def _parse_simple_map(payload: dict[str, Any]) -> dict[str, int]:
    parsed: dict[str, int] = {}
    for alias, emoji_id_raw in payload.items():
        if not isinstance(alias, str):
            continue
        normalized = _normalize_alias(alias)
        if not normalized:
            continue
        try:
            emoji_id = int(emoji_id_raw)
        except (TypeError, ValueError):
            continue
        if emoji_id <= 0:
            continue
        parsed[normalized] = emoji_id
    return parsed


def _parse_emoji_entries(entries: list[Any]) -> dict[str, int]:
    parsed: dict[str, int] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        raw_id = entry.get("id")
        if raw_id is None:
            continue
        try:
            emoji_id = int(raw_id)
        except (TypeError, ValueError):
            continue
        if emoji_id <= 0:
            continue
        aliases_raw = entry.get("aliases")
        if not isinstance(aliases_raw, list):
            continue
        for alias in aliases_raw:
            if not isinstance(alias, str):
                continue
            normalized = _normalize_alias(alias)
            if normalized:
                parsed[normalized] = emoji_id
    return parsed


def _load_external_map(path: Path) -> dict[str, int]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}

    if isinstance(payload, dict):
        # 格式 A：{ "点赞": 76, "👍": 76 }
        if "emojis" not in payload:
            return _parse_simple_map(payload)
        # 格式 B：{ "emojis": [ { "id": 76, "aliases": ["点赞", "👍"] } ] }
        emojis_raw = payload.get("emojis")
        if isinstance(emojis_raw, list):
            return _parse_emoji_entries(emojis_raw)
        return {}

    # 格式 C：[ { "id": 76, "aliases": ["点赞", "👍"] } ]
    if isinstance(payload, list):
        return _parse_emoji_entries(payload)

    return {}


def get_emoji_alias_map() -> dict[str, int]:
    """获取 alias -> emoji_id 映射。

    优先级：内置映射 < 外部映射（后加载覆盖前加载）。
    """
    merged = dict(_DEFAULT_ALIAS_TO_ID)
    for path in _MAP_PATHS:
        if not path.exists():
            continue
        merged.update(_load_external_map(path))
    return merged


def resolve_emoji_id_by_alias(alias: str) -> int | None:
    normalized = _normalize_alias(alias)
    if not normalized:
        return None
    return get_emoji_alias_map().get(normalized)


def search_emoji_aliases(keyword: str, limit: int = 20) -> list[tuple[str, int]]:
    """按关键字搜索 alias。"""
    normalized = _normalize_alias(keyword)
    if not normalized:
        return []
    result: list[tuple[str, int]] = []
    for alias, emoji_id in get_emoji_alias_map().items():
        if normalized in alias:
            result.append((alias, emoji_id))
    result.sort(key=lambda item: (item[1], item[0]))
    if limit <= 0:
        return result
    return result[:limit]


def get_emoji_id_entries() -> list[tuple[int, list[str]]]:
    """返回按 emoji_id 聚合后的条目。"""
    by_id: dict[int, set[str]] = {}
    for alias, emoji_id in get_emoji_alias_map().items():
        by_id.setdefault(emoji_id, set()).add(alias)

    entries: list[tuple[int, list[str]]] = []
    for emoji_id in sorted(by_id):
        aliases = sorted(by_id[emoji_id])
        entries.append((emoji_id, aliases))
    return entries


def get_external_map_paths() -> list[str]:
    return [str(path) for path in _MAP_PATHS]
