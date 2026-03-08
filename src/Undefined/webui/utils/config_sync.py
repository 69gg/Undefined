from __future__ import annotations

import copy
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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
        elif _is_array_of_tables(default_value) and _is_array_of_tables(current_value):
            if not default_value or not current_value:
                continue
            template_item = default_value[0]
            for index, current_item in enumerate(current_value):
                default_item = (
                    default_value[index]
                    if index < len(default_value)
                    else template_item
                )
                added.extend(
                    _collect_added_paths(
                        default_item,
                        current_item,
                        f"{path}[{index}]",
                    )
                )
    return added


def _is_array_of_tables(value: Any) -> bool:
    return (
        isinstance(value, list)
        and bool(value)
        and all(isinstance(item, dict) for item in value)
    )


def _get_nested_value(data: TomlData, path: tuple[str, ...]) -> Any:
    node: Any = data
    for key in path:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
        if node is None:
            return None
    return node


def _prepare_pool_model_templates(
    example_data: TomlData,
    current_data: TomlData,
) -> TomlData:
    prepared = copy.deepcopy(example_data)

    for model_kind in ("chat", "agent"):
        current_models = _get_nested_value(
            current_data,
            ("models", model_kind, "pool", "models"),
        )
        example_models = _get_nested_value(
            prepared,
            ("models", model_kind, "pool", "models"),
        )
        model_table = _get_nested_value(prepared, ("models", model_kind))

        if not (_is_array_of_tables(current_models) and current_models):
            continue
        if example_models != []:
            continue
        if not isinstance(model_table, dict):
            continue

        template = {
            key: copy.deepcopy(value)
            for key, value in model_table.items()
            if key != "pool"
        }
        pool_table = model_table.get("pool")
        if not isinstance(pool_table, dict):
            continue
        pool_table["models"] = [template]

    return prepared


def _augment_pool_model_comments(
    example_comments: CommentMap,
    example_data: TomlData,
    current_data: TomlData,
) -> CommentMap:
    merged: CommentMap = dict(example_comments)
    for model_kind in ("chat", "agent"):
        current_models = _get_nested_value(
            current_data,
            ("models", model_kind, "pool", "models"),
        )
        example_models = _get_nested_value(
            example_data,
            ("models", model_kind, "pool", "models"),
        )
        if not (_is_array_of_tables(current_models) and current_models):
            continue
        if example_models != []:
            continue

        source_prefix = f"models.{model_kind}"
        target_prefix = f"models.{model_kind}.pool.models"
        for path, value in example_comments.items():
            if path == source_prefix:
                merged[target_prefix] = dict(value)
                continue
            if not path.startswith(f"{source_prefix}."):
                continue
            suffix = path.removeprefix(source_prefix)
            if suffix.startswith(".pool"):
                continue
            merged[f"{target_prefix}{suffix}"] = dict(value)

    return merged


def _merge_comment_maps(current: CommentMap, example: CommentMap) -> CommentMap:
    merged: CommentMap = dict(current)
    for key, value in example.items():
        merged[key] = dict(value)
    return merged


def sync_config_text(current_text: str, example_text: str) -> ConfigTemplateSyncResult:
    current_data = _parse_toml_text(current_text, label="current config")
    example_data = _parse_toml_text(example_text, label="config example")
    prepared_example_data = _prepare_pool_model_templates(example_data, current_data)
    added_paths = _collect_added_paths(prepared_example_data, current_data)
    merged = merge_defaults(prepared_example_data, current_data)
    example_comments = parse_comment_map_text(example_text)
    comments = _merge_comment_maps(
        parse_comment_map_text(current_text),
        _augment_pool_model_comments(example_comments, example_data, current_data),
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
