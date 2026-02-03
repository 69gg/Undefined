from __future__ import annotations

import logging
import tomllib
from pathlib import Path
from typing import Any

from Undefined.config.loader import CONFIG_PATH, Config

logger = logging.getLogger(__name__)

CONFIG_EXAMPLE_PATH = Path("config.toml.example")

TomlData = dict[str, Any]
CommentMap = dict[str, dict[str, str]]

SECTION_ORDER: dict[str, list[str]] = {
    "": [
        "core",
        "onebot",
        "models",
        "logging",
        "tools",
        "skills",
        "search",
        "proxy",
        "weather",
        "xxapi",
        "token_usage",
        "mcp",
        "webui",
    ],
    "models": ["chat", "vision", "security", "agent"],
}

KEY_ORDER: dict[str, list[str]] = {
    "core": ["bot_qq", "superadmin_qq", "admin_qq", "forward_proxy_qq"],
    "onebot": ["ws_url", "token"],
    "logging": ["level", "file_path", "max_size_mb", "backup_count", "log_thinking"],
    "tools": [
        "sanitize",
        "description_max_len",
        "sanitize_verbose",
        "description_preview_len",
    ],
    "skills": [
        "hot_reload",
        "hot_reload_interval",
        "hot_reload_debounce",
        "intro_autogen_enabled",
        "intro_autogen_queue_interval",
        "intro_autogen_max_tokens",
        "intro_hash_path",
        "prefetch_tools",
        "prefetch_tools_hide",
    ],
    "search": ["searxng_url"],
    "proxy": ["use_proxy", "http_proxy", "https_proxy"],
    "weather": ["api_key"],
    "xxapi": ["api_token"],
    "token_usage": [
        "max_size_mb",
        "max_archives",
        "max_total_mb",
        "archive_prune_mode",
    ],
    "mcp": ["config_path"],
    "webui": ["url", "port", "password"],
    "models.chat": [
        "api_url",
        "api_key",
        "model_name",
        "max_tokens",
        "thinking_enabled",
        "thinking_budget_tokens",
        "deepseek_new_cot_support",
    ],
    "models.vision": [
        "api_url",
        "api_key",
        "model_name",
        "thinking_enabled",
        "thinking_budget_tokens",
        "deepseek_new_cot_support",
    ],
    "models.security": [
        "api_url",
        "api_key",
        "model_name",
        "max_tokens",
        "thinking_enabled",
        "thinking_budget_tokens",
        "deepseek_new_cot_support",
    ],
    "models.agent": [
        "api_url",
        "api_key",
        "model_name",
        "max_tokens",
        "thinking_enabled",
        "thinking_budget_tokens",
        "deepseek_new_cot_support",
    ],
}


def read_config_source() -> dict[str, Any]:
    if CONFIG_PATH.exists():
        return {
            "content": CONFIG_PATH.read_text(encoding="utf-8"),
            "exists": True,
            "source": str(CONFIG_PATH),
        }
    if CONFIG_EXAMPLE_PATH.exists():
        return {
            "content": CONFIG_EXAMPLE_PATH.read_text(encoding="utf-8"),
            "exists": False,
            "source": str(CONFIG_EXAMPLE_PATH),
        }
    return {
        "content": "[core]\nbot_qq = 0\nsuperadmin_qq = 0\n",
        "exists": False,
        "source": "inline",
    }


def validate_toml(content: str) -> tuple[bool, str]:
    try:
        tomllib.loads(content)
        return True, "OK"
    except tomllib.TOMLDecodeError as exc:
        return False, f"TOML parse error: {exc}"


def validate_required_config() -> tuple[bool, str]:
    try:
        Config.load(strict=True)
        return True, "OK"
    except Exception as exc:
        return False, str(exc)


def load_default_data() -> TomlData:
    if not CONFIG_EXAMPLE_PATH.exists():
        return {}
    try:
        with open(CONFIG_EXAMPLE_PATH, "rb") as f:
            data = tomllib.load(f)
        if isinstance(data, dict):
            return data
        return {}
    except Exception:
        return {}


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
        if "zh" not in result:
            result["zh"] = default
        if "en" not in result:
            result["en"] = default
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
            if buffer:
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
        if buffer:
            buffer.clear()
    return comments


def load_comment_map() -> CommentMap:
    comments = parse_comment_map(CONFIG_EXAMPLE_PATH)
    if CONFIG_PATH.exists():
        overrides = parse_comment_map(CONFIG_PATH)
        for key, value in overrides.items():
            if key not in comments:
                comments[key] = value
                continue
            merged = dict(comments[key])
            merged.update(value)
            comments[key] = merged
    return comments


def merge_defaults(defaults: TomlData, data: TomlData) -> TomlData:
    merged: TomlData = dict(defaults)
    for key, value in data.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = merge_defaults(merged[key], value)
        else:
            merged[key] = value
    return merged


def sort_config(data: TomlData) -> TomlData:
    """按 SECTION_ORDER 和 KEY_ORDER 排序配置"""
    ordered: TomlData = {}
    sections = SECTION_ORDER.get("", [])
    # 保证指定顺序的 section 在前面
    for s in sections:
        if s in data:
            val = data[s]
            if isinstance(val, dict):
                sub_ordered: TomlData = {}
                keys = KEY_ORDER.get(s, [])
                for k in keys:
                    if k in val:
                        sub_ordered[k] = val[k]
                for k in sorted(val.keys()):
                    if k not in sub_ordered:
                        sub_ordered[k] = val[k]
                ordered[s] = sub_ordered
            else:
                ordered[s] = val
    # 添加剩余的 section
    for s in sorted(data.keys()):
        if s not in ordered:
            ordered[s] = data[s]
    return ordered


def sorted_keys(table: TomlData, path: list[str]) -> list[str]:
    path_key = ".".join(path) if path else ""
    order = KEY_ORDER.get(path_key) or SECTION_ORDER.get(path_key)
    if not order:
        return sorted(table.keys())
    order_index = {name: idx for idx, name in enumerate(order)}
    return sorted(
        table.keys(),
        key=lambda name: (order_index.get(name, 999), name),
    )


def format_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    if isinstance(value, list):
        items = ", ".join(format_value(item) for item in value)
        return f"[{items}]"
    return f'"{str(value)}"'


def render_table(path: list[str], table: TomlData) -> list[str]:
    lines: list[str] = []
    items: list[str] = []
    for key in sorted_keys(table, path):
        value = table[key]
        if isinstance(value, dict):
            continue
        items.append(f"{key} = {format_value(value)}")
    if items and path:
        lines.append(f"[{'.'.join(path)}]")
        lines.extend(items)
        lines.append("")
    elif items and not path:
        lines.extend(items)
        lines.append("")

    for key in sorted_keys(table, path):
        value = table[key]
        if not isinstance(value, dict):
            continue
        lines.extend(render_table(path + [key], value))
    return lines


def render_toml(data: TomlData) -> str:
    if not data:
        return ""
    lines = render_table([], data)
    return "\n".join(lines).rstrip() + "\n"


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


def tail_file(path: Path, lines: int) -> str:
    if lines <= 0:
        return ""
    if not path.exists():
        return f"Log file not found: {path}"
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            file_size = f.tell()
            block_size = 4096
            data = bytearray()
            remaining = file_size
            while remaining > 0 and data.count(b"\n") <= lines:
                read_size = min(block_size, remaining)
                f.seek(remaining - read_size)
                chunk = f.read(read_size)
                data[:0] = chunk
                remaining -= read_size

            # 使用 errors='replace' 防止截断导致的 unicode 错误
            text = data.decode("utf-8", errors="replace")
            # 确保只返回最后 N 行
            return "\n".join(text.splitlines()[-lines:])
    except Exception as exc:
        return f"Failed to read logs: {exc}"
