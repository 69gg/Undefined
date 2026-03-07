from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from Undefined.config.loader import CONFIG_PATH

from .comment import CommentMap, parse_comment_map_text
from .config_io import CONFIG_EXAMPLE_PATH, _resolve_config_example_path
from .toml_render import TomlData, merge_defaults, render_toml


@dataclass(frozen=True)
class ConfigTemplateSyncResult:
    content: str
    added_paths: list[str]
    comments: CommentMap


def _parse_toml_text(content: str, *, label: str) -> TomlData:
    if not content.strip():
        return {}
    try:
        data = tomllib.loads(content)
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"{label} TOML parse error: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{label} TOML root must be a table")
    return data


def _collect_added_paths(
    defaults: TomlData, current: TomlData, prefix: str = ""
) -> list[str]:
    added: list[str] = []
    for key, default_value in defaults.items():
        path = f"{prefix}.{key}" if prefix else key
        if key not in current:
            added.append(path)
            continue
        current_value = current[key]
        if isinstance(default_value, dict) and isinstance(current_value, dict):
            added.extend(_collect_added_paths(default_value, current_value, path))
    return added


def _merge_comment_maps(current: CommentMap, example: CommentMap) -> CommentMap:
    merged: CommentMap = dict(current)
    for key, value in example.items():
        merged[key] = dict(value)
    return merged


def sync_config_text(current_text: str, example_text: str) -> ConfigTemplateSyncResult:
    current_data = _parse_toml_text(current_text, label="current config")
    example_data = _parse_toml_text(example_text, label="config example")
    added_paths = _collect_added_paths(example_data, current_data)
    merged = merge_defaults(example_data, current_data)
    comments = _merge_comment_maps(
        parse_comment_map_text(current_text),
        parse_comment_map_text(example_text),
    )
    content = render_toml(merged, comments=comments)
    return ConfigTemplateSyncResult(
        content=content,
        added_paths=added_paths,
        comments=comments,
    )


def sync_config_file(
    config_path: Path = CONFIG_PATH,
    example_path: Path = CONFIG_EXAMPLE_PATH,
    *,
    write: bool = True,
) -> ConfigTemplateSyncResult:
    resolved_example = _resolve_config_example_path(example_path)
    if resolved_example is None or not resolved_example.exists():
        raise FileNotFoundError(f"config example not found: {example_path}")

    current_text = (
        config_path.read_text(encoding="utf-8") if config_path.exists() else ""
    )
    example_text = resolved_example.read_text(encoding="utf-8")
    result = sync_config_text(current_text, example_text)
    if write:
        config_path.write_text(result.content, encoding="utf-8")
    return result
