"""TOML file I/O and environment bootstrap for configuration."""

from __future__ import annotations

# 配置 I/O：读取 config.toml、加载 .env bootstrap、格式化解析错误

import logging
import os
import re
import tomllib
from pathlib import Path
from typing import Any, IO, Optional

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover
    StrPath = str | os.PathLike[str]

    def load_dotenv(
        dotenv_path: StrPath | None = None,
        stream: IO[str] | None = None,
        verbose: bool = False,
        override: bool = False,
        interpolate: bool = True,
        encoding: str | None = "utf-8",
    ) -> bool:
        return False


logger = logging.getLogger(__name__)

CONFIG_PATH = Path("config.toml")

__all__ = ["CONFIG_PATH", "_load_env", "load_toml_data"]


def _load_env() -> None:
    # dotenv 仅 bootstrap 环境变量，不覆盖已有 os.environ（TOML 仍优先于 env）
    try:
        load_dotenv()
    except Exception:
        logger.debug("加载 .env 失败，继续使用 config.toml", exc_info=True)


def _build_toml_decode_hint(line: str) -> str:
    """根据出错行内容生成 TOML 修复提示。"""
    hints: list[str] = []
    if "\\" in line:
        hints.append(
            'Windows 路径建议用单引号(不转义)或双反斜杠，或直接用正斜杠，例如：path = \'D:\\AI\\bot\' / path = "D:\\\\AI\\\\bot" / path = "D:/AI/bot"'
        )
    hints.append('多行文本请用三引号，例如：prompt = """..."""')
    return "；".join(hints)


def _format_toml_decode_error(
    path: Path, text: str, exc: tomllib.TOMLDecodeError
) -> str:
    """将 tomllib 解析异常格式化为带行号、caret 与中文提示的可读消息。"""
    lineno: int | None = getattr(exc, "lineno", None)
    colno: int | None = getattr(exc, "colno", None)
    if not isinstance(lineno, int) or not isinstance(colno, int):
        match = re.search(r"\(at line (\d+), column (\d+)\)", str(exc))
        if match:
            lineno = int(match.group(1))
            colno = int(match.group(2))

    if isinstance(lineno, int) and lineno > 0:
        lines = text.splitlines()
        line = lines[lineno - 1] if 0 <= (lineno - 1) < len(lines) else ""
        caret_pos = max((colno or 1) - 1, 0)
        caret = " " * min(caret_pos, len(line)) + "^"
        hint = _build_toml_decode_hint(line)
        location = f"line={lineno} col={colno or 1}"
        return f"{exc} ({location})\n> {line}\n  {caret}\n提示：{hint}"
    return str(exc)


def load_toml_data(
    config_path: Optional[Path] = None, *, strict: bool = False
) -> dict[str, Any]:
    """读取 config.toml 并返回字典；文件不存在时返回空 dict。"""
    path = config_path or CONFIG_PATH
    if not path.exists():
        return {}
    text = ""
    try:
        # utf-8-sig 兼容带 BOM 的编辑器输出
        text = path.read_bytes().decode("utf-8-sig")
        data = tomllib.loads(text)
        if isinstance(data, dict):
            return data
        logger.warning("config.toml 内容不是对象结构")
        return {}
    except tomllib.TOMLDecodeError as exc:
        message = _format_toml_decode_error(path, text, exc)
        logger.error("config.toml 解析失败 (%s): %s", path.resolve(), message)
        if strict:
            raise ValueError(message) from exc
        return {}
    except UnicodeDecodeError as exc:
        logger.error("config.toml 编码错误 (%s): %s", path.resolve(), exc)
        if strict:
            raise ValueError(str(exc)) from exc
        return {}
    except OSError as exc:
        logger.error("读取 config.toml 失败: %s", exc)
        if strict:
            raise ValueError(str(exc)) from exc
        return {}
