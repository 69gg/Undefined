import re
from pathlib import Path
from typing import Any

_CONTEXT_KEY_CACHE: set[str] | None = None
_SCAN_PATHS: list[Path] = []
_SCAN_EXTENSIONS: tuple[str, ...] = (".py",)


def set_context_resource_scan_paths(paths: list[Path]) -> None:
    global _SCAN_PATHS
    _SCAN_PATHS = paths


def _scan_context_keys() -> set[str]:
    keys: set[str] = set()
    if not _SCAN_PATHS:
        return keys

    pattern_get = re.compile(r'context\.get\(\s*["\']([^"\']+)["\']')
    pattern_get_resource = re.compile(r'context\.get_resource\(\s*["\']([^"\']+)["\']')

    for base_dir in _SCAN_PATHS:
        if not base_dir.exists():
            continue
        for path in base_dir.rglob("*"):
            if not path.is_file() or path.suffix not in _SCAN_EXTENSIONS:
                continue
            try:
                content = path.read_text(encoding="utf-8")
            except Exception:
                continue
            for match in pattern_get.findall(content):
                keys.add(match)
            for match in pattern_get_resource.findall(content):
                keys.add(match)

    return keys


def get_context_resource_keys() -> set[str]:
    global _CONTEXT_KEY_CACHE
    if _CONTEXT_KEY_CACHE is None:
        _CONTEXT_KEY_CACHE = _scan_context_keys()
    return _CONTEXT_KEY_CACHE


def refresh_context_resource_keys() -> None:
    global _CONTEXT_KEY_CACHE
    _CONTEXT_KEY_CACHE = _scan_context_keys()


def collect_context_resources(local_vars: dict[str, Any]) -> dict[str, Any]:
    resources: dict[str, Any] = {}
    for key in get_context_resource_keys():
        if key in local_vars:
            value = local_vars[key]
            if value is not None:
                resources[key] = value
    return resources
