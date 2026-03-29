from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PaperInfo:
    paper_id: str
    title: str
    authors: tuple[str, ...]
    summary: str
    published: str
    updated: str
    primary_category: str
    abs_url: str
    pdf_url: str
