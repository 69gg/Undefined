"""文本分块：按行切分，忽略空行。"""

from __future__ import annotations


def split_lines(text: str) -> list[str]:
    """按行切分文本，忽略空行，返回非空行列表。"""
    return [line for line in text.splitlines() if line.strip()]
