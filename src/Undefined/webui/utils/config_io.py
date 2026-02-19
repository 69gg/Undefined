from __future__ import annotations

import logging
import tomllib
from pathlib import Path
from typing import Any

from Undefined.config.loader import CONFIG_PATH, Config
from Undefined.utils.resources import resolve_resource_path

logger = logging.getLogger(__name__)

CONFIG_EXAMPLE_PATH = Path("config.toml.example")
TomlData = dict[str, Any]


def _resolve_config_example_path(path: Path = CONFIG_EXAMPLE_PATH) -> Path | None:
    if path.exists():
        return path
    try:
        return resolve_resource_path(str(path))
    except Exception:
        return None


def read_config_source() -> dict[str, Any]:
    if CONFIG_PATH.exists():
        return {
            "content": CONFIG_PATH.read_text(encoding="utf-8"),
            "exists": True,
            "source": str(CONFIG_PATH),
        }
    example_path = _resolve_config_example_path()
    if example_path is not None and example_path.exists():
        return {
            "content": example_path.read_text(encoding="utf-8"),
            "exists": False,
            "source": str(example_path),
        }
    return {
        "content": "[core]\nbot_qq = 0\nsuperadmin_qq = 0\n",
        "exists": False,
        "source": "inline",
    }


def ensure_config_toml(
    config_path: Path = CONFIG_PATH,
    example_path: Path = CONFIG_EXAMPLE_PATH,
) -> bool:
    if config_path.exists():
        return False
    resolved_example = _resolve_config_example_path(example_path)
    content = ""
    if resolved_example is not None and resolved_example.exists():
        try:
            content = resolved_example.read_text(encoding="utf-8")
        except Exception as exc:
            logger.warning("读取 %s 失败，将使用内置模板: %s", resolved_example, exc)
    if not content.strip():
        content = "[core]\nbot_qq = 0\nsuperadmin_qq = 0\n"
    try:
        with open(config_path, "x", encoding="utf-8") as f:
            f.write(content)
        logger.info(
            "已生成 %s（来源：%s）", config_path, resolved_example or example_path
        )
        return True
    except FileExistsError:
        return False
    except Exception as exc:
        logger.warning("生成 %s 失败: %s", config_path, exc)
        return False


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
    example_path = _resolve_config_example_path()
    if example_path is None or not example_path.exists():
        return {}
    try:
        with open(example_path, "rb") as f:
            data = tomllib.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


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
                data[:0] = f.read(read_size)
                remaining -= read_size
        return "\n".join(data.decode("utf-8", errors="replace").splitlines()[-lines:])
    except Exception as exc:
        return f"Failed to read logs: {exc}"
