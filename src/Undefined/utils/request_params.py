from __future__ import annotations

from typing import Any, Mapping


def _clone_json_like(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _clone_json_like(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_clone_json_like(item) for item in value]
    if isinstance(value, tuple):
        return [_clone_json_like(item) for item in value]
    return str(value)


def normalize_request_params(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    return {str(key): _clone_json_like(item) for key, item in value.items()}


def merge_request_params(*values: Any) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for value in values:
        if not isinstance(value, Mapping):
            continue
        merged.update(normalize_request_params(value))
    return merged


def split_reserved_request_params(
    params: Mapping[str, Any] | None,
    reserved_keys: set[str] | frozenset[str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    normalized = normalize_request_params(params)
    allowed: dict[str, Any] = {}
    reserved: dict[str, Any] = {}
    for key, value in normalized.items():
        if key in reserved_keys:
            reserved[key] = value
        else:
            allowed[key] = value
    return allowed, reserved
