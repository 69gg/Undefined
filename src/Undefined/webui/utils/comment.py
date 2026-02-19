from __future__ import annotations

from pathlib import Path

from Undefined.config.loader import CONFIG_PATH
from .config_io import _resolve_config_example_path

CommentMap = dict[str, dict[str, str]]


def _normalize_comment_buffer(buffer: list[str]) -> dict[str, str]:
    if not buffer:
        return {}
    parts: dict[str, list[str]] = {}
    for item in buffer:
        lower = item.lower()
        if lower.startswith("zh:"):
            parts.setdefault("zh", []).append(item[3:].strip())
        elif lower.startswith("en:"):
            parts.setdefault("en", []).append(item[3:].strip())
        else:
            parts.setdefault("default", []).append(item)
    default = " ".join(parts.get("default", [])).strip()
    zh_value = " ".join(parts.get("zh", [])).strip()
    en_value = " ".join(parts.get("en", [])).strip()
    result: dict[str, str] = {}
    if zh_value:
        result["zh"] = zh_value
    if en_value:
        result["en"] = en_value
    if default:
        result.setdefault("zh", default)
        result.setdefault("en", default)
    return result


def parse_comment_map(path: Path) -> CommentMap:
    if not path.exists():
        return {}
    comments: CommentMap = {}
    buffer: list[str] = []
    current_section = ""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return {}
    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            buffer.clear()
            continue
        if line.startswith("#"):
            buffer.append(line.lstrip("#").strip())
            continue
        if line.startswith("[") and line.endswith("]"):
            section_name = line[1:-1].strip()
            if buffer:
                comment = _normalize_comment_buffer(buffer)
                if comment:
                    comments[section_name] = comment
                buffer.clear()
            current_section = section_name
            continue
        if "=" in line:
            key = line.split("=", 1)[0].strip()
            if buffer:
                comment = _normalize_comment_buffer(buffer)
                if comment:
                    path_key = f"{current_section}.{key}" if current_section else key
                    comments[path_key] = comment
                buffer.clear()
            continue
        buffer.clear()
    return comments


def load_comment_map() -> CommentMap:
    example_path = _resolve_config_example_path()
    comments = parse_comment_map(example_path) if example_path else {}
    if CONFIG_PATH.exists():
        for key, value in parse_comment_map(CONFIG_PATH).items():
            if key not in comments:
                comments[key] = value
            else:
                merged = dict(comments[key])
                merged.update(value)
                comments[key] = merged
    return comments
