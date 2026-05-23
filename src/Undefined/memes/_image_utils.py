"""Meme 图片处理与标签归一化共享工具。"""

from __future__ import annotations

import math
import mimetypes
import re
from datetime import datetime
from pathlib import Path

from openai import APIConnectionError, APIStatusError, APITimeoutError
from PIL import Image

from Undefined.memes.models import normalize_string_list

_IMAGE_EXTENSIONS_BY_MIME = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/bmp": ".bmp",
    "image/svg+xml": ".svg",
}
_TAG_SPLIT_RE = re.compile(r"[,，\n]+")


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def guess_suffix(path: Path, mime_type: str) -> str:
    suffix = path.suffix.lower()
    if suffix:
        return suffix
    guessed = _IMAGE_EXTENSIONS_BY_MIME.get(mime_type)
    if guessed:
        return guessed
    mime_guess = mimetypes.guess_extension(mime_type or "")
    if mime_guess:
        return mime_guess.lower()
    return ".bin"


def normalize_tags(raw_tags: list[str] | str | None) -> list[str]:
    if raw_tags is None:
        return []
    if isinstance(raw_tags, str):
        parts = [part.strip() for part in _TAG_SPLIT_RE.split(raw_tags)]
        return normalize_string_list(parts)
    return normalize_string_list(raw_tags)


def is_retryable_llm_error(exc: Exception) -> bool:
    """判断 LLM 调用异常是否应触发 worker 级重试。"""
    if isinstance(exc, (APIConnectionError, APITimeoutError)):
        return True
    if isinstance(exc, APIStatusError):
        return exc.status_code == 429 or exc.status_code >= 500
    return False


def extract_gif_frames(source_path: Path, n_frames: int) -> list[Image.Image]:
    """从 GIF 中均匀采样 *n_frames* 帧（含首末帧），返回 RGBA Image 列表。"""
    with Image.open(source_path) as image:
        total = getattr(image, "n_frames", 1)
        if total <= 1:
            image.seek(0)
            return [image.convert("RGBA").copy()]
        n = min(n_frames, total)
        if n <= 1:
            image.seek(0)
            return [image.convert("RGBA").copy()]
        indices = sample_frame_indices(total, n)
        frames: list[Image.Image] = []
        for idx in indices:
            image.seek(idx)
            frames.append(image.convert("RGBA").copy())
        return frames


def sample_frame_indices(total: int, n: int) -> list[int]:
    """生成均匀采样的帧索引列表（始终包含首帧和末帧）。"""
    if n >= total:
        return list(range(total))
    if n == 1:
        return [0]
    if n == 2:
        return [0, total - 1]
    indices = [round(i * (total - 1) / (n - 1)) for i in range(n)]
    seen: set[int] = set()
    result: list[int] = []
    for idx in indices:
        if idx not in seen:
            seen.add(idx)
            result.append(idx)
    return result


def compose_grid(frames: list[Image.Image], output_path: Path) -> None:
    """将多帧拼接为网格图并保存为 PNG。"""
    n = len(frames)
    if n == 0:
        return
    if n == 1:
        frames[0].save(output_path, format="PNG")
        return
    cols = math.ceil(math.sqrt(n))
    rows = math.ceil(n / cols)
    fw, fh = frames[0].size
    grid = Image.new("RGBA", (cols * fw, rows * fh), (0, 0, 0, 0))
    for i, frame in enumerate(frames):
        resized = (
            frame.resize((fw, fh), Image.Resampling.LANCZOS)
            if frame.size != (fw, fh)
            else frame
        )
        x = (i % cols) * fw
        y = (i // cols) * fh
        grid.paste(resized, (x, y))
    grid.save(output_path, format="PNG")


# 向后兼容：旧模块级私有名仍可从 service 等路径导入
_now_iso = now_iso
_guess_suffix = guess_suffix
_normalize_tags = normalize_tags
_is_retryable_llm_error = is_retryable_llm_error
_extract_gif_frames = extract_gif_frames
_sample_frame_indices = sample_frame_indices
_compose_grid = compose_grid

__all__ = [
    "compose_grid",
    "extract_gif_frames",
    "guess_suffix",
    "is_retryable_llm_error",
    "normalize_tags",
    "now_iso",
    "sample_frame_indices",
    "_compose_grid",
    "_extract_gif_frames",
    "_guess_suffix",
    "_is_retryable_llm_error",
    "_normalize_tags",
    "_now_iso",
    "_sample_frame_indices",
]
