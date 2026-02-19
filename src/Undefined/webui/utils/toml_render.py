from __future__ import annotations

from functools import lru_cache
from typing import Any, cast

from .config_io import load_default_data

TomlData = dict[str, Any]
OrderMap = dict[str, list[str]]


def _build_order_map(
    table: TomlData, path: list[str] | None = None, out: OrderMap | None = None
) -> OrderMap:
    if out is None:
        out = {}
    if path is None:
        path = []
    path_key = ".".join(path) if path else ""
    out[path_key] = list(table.keys())
    for key, value in table.items():
        if isinstance(value, dict):
            _build_order_map(cast(TomlData, value), path + [key], out)
    return out


@lru_cache
def get_config_order_map() -> OrderMap:
    defaults = load_default_data()
    if not defaults:
        return {}
    return _build_order_map(defaults)


def sorted_keys(table: TomlData, path: list[str]) -> list[str]:
    path_key = ".".join(path) if path else ""
    order = get_config_order_map().get(path_key)
    if not order:
        return sorted(table.keys())
    order_index = {name: idx for idx, name in enumerate(order)}
    return sorted(table.keys(), key=lambda name: (order_index.get(name, 999), name))


def format_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return f'"{value.replace(chr(92), chr(92) * 2).replace(chr(34), chr(92) + chr(34))}"'
    if isinstance(value, list):
        return f"[{', '.join(format_value(item) for item in value)}]"
    return f'"{str(value)}"'


def _is_array_of_tables(value: Any) -> bool:
    return (
        isinstance(value, list)
        and bool(value)
        and all(isinstance(i, dict) for i in value)
    )


def render_table(path: list[str], table: TomlData) -> list[str]:
    lines: list[str] = []
    items = [
        f"{key} = {format_value(table[key])}"
        for key in sorted_keys(table, path)
        if not isinstance(table[key], dict) and not _is_array_of_tables(table[key])
    ]
    if items and path:
        lines.append(f"[{'.'.join(path)}]")
        lines.extend(items)
        lines.append("")
    elif items:
        lines.extend(items)
        lines.append("")
    for key in sorted_keys(table, path):
        value = table[key]
        if isinstance(value, dict):
            lines.extend(render_table(path + [key], value))
        elif _is_array_of_tables(value):
            aot_path = ".".join(path + [key])
            for item in value:
                lines.append(f"[[{aot_path}]]")
                for k in sorted_keys(item, path + [key]):
                    v = item[k]
                    if not isinstance(v, dict):
                        lines.append(f"{k} = {format_value(v)}")
                lines.append("")
    return lines


def render_toml(data: TomlData) -> str:
    if not data:
        return ""
    return "\n".join(render_table([], data)).rstrip() + "\n"


def apply_patch(data: TomlData, patch: dict[str, Any]) -> TomlData:
    for path, value in patch.items():
        if not path:
            continue
        parts = path.split(".")
        node = data
        for key in parts[:-1]:
            if key not in node or not isinstance(node[key], dict):
                node[key] = {}
            node = node[key]
        node[parts[-1]] = value
    return data


def merge_defaults(defaults: TomlData, data: TomlData) -> TomlData:
    merged: TomlData = dict(defaults)
    for key, value in data.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = merge_defaults(merged[key], value)
        else:
            merged[key] = value
    return merged


def sort_config(data: TomlData) -> TomlData:
    order_map = get_config_order_map()
    ordered: TomlData = {}
    for s in order_map.get("", []):
        if s in data:
            val = data[s]
            if isinstance(val, dict):
                sub: TomlData = {}
                for k in order_map.get(s, []):
                    if k in val:
                        sub[k] = val[k]
                for k in sorted(val.keys()):
                    if k not in sub:
                        sub[k] = val[k]
                ordered[s] = sub
            else:
                ordered[s] = val
    for s in sorted(data.keys()):
        if s not in ordered:
            ordered[s] = data[s]
    return ordered
