from __future__ import annotations

import logging
import tomllib
from pathlib import Path
from typing import Any

from Undefined.config.loader import CONFIG_PATH, Config

logger = logging.getLogger(__name__)

CONFIG_EXAMPLE_PATH = Path("config.toml.example")

TomlData = dict[str, Any]


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
