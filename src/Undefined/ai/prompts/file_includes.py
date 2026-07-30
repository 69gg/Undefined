"""将本地 UTF-8 文件插入主 Prompt 的稳定命名插槽。"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
import logging
from pathlib import Path
import re

from Undefined.config.models import PROMPT_FILE_INCLUDE_SLOTS
from Undefined.utils.io import read_text

logger = logging.getLogger(__name__)

_PROMPT_FILE_INCLUDE_MARKER_RE = re.compile(
    r"^[ \t]*<!--\s*undefined:prompt-file-include:"
    r"(?P<slot>[a-z0-9_-]+)\s*-->[ \t]*(?:\r?\n|$)",
    re.MULTILINE,
)


async def _read_include_file(slot: str, raw_path: str) -> str:
    path = Path(raw_path).expanduser()
    try:
        content = await read_text(path)
    except (OSError, UnicodeError) as exc:
        logger.warning(
            "[Prompt] 文件插槽读取失败，已跳过: slot=%s path=%s error=%s",
            slot,
            path,
            exc,
        )
        return ""
    if content is None:
        logger.warning(
            "[Prompt] 文件插槽不存在，已跳过: slot=%s path=%s",
            slot,
            path,
        )
        return ""
    return content


async def apply_prompt_file_includes(
    prompt: str,
    includes: Mapping[str, str] | None,
) -> str:
    """替换 Prompt 中的文件插槽；文件内容只处理一轮，不递归展开。"""
    markers = list(_PROMPT_FILE_INCLUDE_MARKER_RE.finditer(prompt))
    marker_slots = {match.group("slot") for match in markers}
    configured = {
        slot: path.strip()
        for slot, path in (includes or {}).items()
        if slot in PROMPT_FILE_INCLUDE_SLOTS and isinstance(path, str) and path.strip()
    }

    unused_slots = sorted(set(configured) - marker_slots)
    if unused_slots:
        logger.warning(
            "[Prompt] 已配置的文件插槽在当前主提示词中不存在，已跳过: %s",
            ", ".join(unused_slots),
        )

    slots_to_load = sorted(marker_slots & set(configured))
    loaded_contents = await asyncio.gather(
        *(_read_include_file(slot, configured[slot]) for slot in slots_to_load)
    )
    contents = dict(zip(slots_to_load, loaded_contents, strict=True))

    def replace_marker(match: re.Match[str]) -> str:
        content = contents.get(match.group("slot"), "")
        if not content:
            return ""
        return content if content.endswith(("\n", "\r")) else f"{content}\n"

    return _PROMPT_FILE_INCLUDE_MARKER_RE.sub(replace_marker, prompt)


__all__ = ["apply_prompt_file_includes"]
