"""文本分块：滑动窗口切分。"""

from __future__ import annotations


def chunk_lines(text: str, window: int = 10, overlap: int = 2) -> list[str]:
    """按滑动窗口切分文本，返回每个窗口合并后的字符串列表。"""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return []
    step = max(1, window - overlap)
    return ["\n".join(lines[i : i + window]) for i in range(0, len(lines), step)]
