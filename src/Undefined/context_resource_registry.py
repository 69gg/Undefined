"""上下文资源注册表。

扫描代码库中使用的上下文资源键，并提供收集上下文资源的功能。
"""

import re
from pathlib import Path
from typing import Any

# 上下文键缓存
_CONTEXT_KEY_CACHE: set[str] | None = None

# 扫描路径列表
_SCAN_PATHS: list[Path] = []

# 扫描的文件扩展名
_SCAN_EXTENSIONS: tuple[str, ...] = (".py",)

# 正则表达式模式
_PATTERN_GET = re.compile(r'context\.get\(\s*["\']([^"\']+)["\']')
_PATTERN_GET_RESOURCE = re.compile(r'context\.get_resource\(\s*["\']([^"\']+)["\']')


def set_context_resource_scan_paths(paths: list[Path]) -> None:
    """设置上下文资源扫描路径。

    Args:
        paths: 要扫描的目录路径列表
    """
    global _SCAN_PATHS
    _SCAN_PATHS = paths


def _scan_file_for_keys(path: Path) -> set[str]:
    """扫描单个文件中的上下文键。

    Args:
        path: 文件路径

    Returns:
        文件中找到的上下文键集合
    """
    keys: set[str] = set()
    try:
        content = path.read_text(encoding="utf-8")
        keys.update(_PATTERN_GET.findall(content))
        keys.update(_PATTERN_GET_RESOURCE.findall(content))
    except Exception:
        pass
    return keys


def _scan_directory_for_keys(base_dir: Path) -> set[str]:
    """扫描目录中的所有 Python 文件。

    Args:
        base_dir: 基础目录路径

    Returns:
        目录中所有文件找到的上下文键集合
    """
    keys: set[str] = set()
    if not base_dir.exists():
        return keys

    for path in base_dir.rglob("*"):
        if not path.is_file() or path.suffix not in _SCAN_EXTENSIONS:
            continue
        keys.update(_scan_file_for_keys(path))

    return keys


def _scan_context_keys() -> set[str]:
    """扫描所有配置路径中的上下文键。

    Returns:
        找到的所有上下文键集合
    """
    keys: set[str] = set()
    if not _SCAN_PATHS:
        return keys

    for base_dir in _SCAN_PATHS:
        keys.update(_scan_directory_for_keys(base_dir))

    return keys


def get_context_resource_keys() -> set[str]:
    """获取所有上下文资源键。

    使用缓存机制，首次调用时扫描文件，后续调用直接返回缓存结果。

    Returns:
        上下文资源键集合
    """
    global _CONTEXT_KEY_CACHE
    if _CONTEXT_KEY_CACHE is None:
        _CONTEXT_KEY_CACHE = _scan_context_keys()
    return _CONTEXT_KEY_CACHE


def refresh_context_resource_keys() -> None:
    """刷新上下文资源键缓存。

    重新扫描文件以更新缓存。
    """
    global _CONTEXT_KEY_CACHE
    _CONTEXT_KEY_CACHE = _scan_context_keys()


def collect_context_resources(local_vars: dict[str, Any]) -> dict[str, Any]:
    """从局部变量中收集上下文资源。

    Args:
        local_vars: 局部变量字典

    Returns:
        包含所有找到的上下文资源的字典
    """
    resources: dict[str, Any] = {}
    for key in get_context_resource_keys():
        if key in local_vars:
            value = local_vars[key]
            if value is not None:
                resources[key] = value
    return resources
