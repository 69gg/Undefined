from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class MemeRecord:
    uid: str
    content_sha256: str
    blob_path: str
    preview_path: str | None
    mime_type: str
    file_size: int
    width: int | None
    height: int | None
    is_animated: bool
    enabled: bool
    pinned: bool
    auto_description: str
    manual_description: str
    ocr_text: str
    tags: list[str] = field(default_factory=list)
    aliases: list[str] = field(default_factory=list)
    search_text: str = ""
    use_count: int = 0
    last_used_at: str = ""
    created_at: str = ""
    updated_at: str = ""
    status: str = "ready"
    segment_data: dict[str, str] = field(default_factory=dict)

    @property
    def description(self) -> str:
        manual = self.manual_description.strip()
        if manual:
            return manual
        return self.auto_description.strip()


@dataclass(frozen=True)
class MemeSourceRecord:
    uid: str
    source_type: str
    chat_type: str
    chat_id: str
    sender_id: str
    message_id: str
    attachment_uid: str
    source_url: str
    seen_at: str


@dataclass(frozen=True)
class MemeSearchItem:
    uid: str
    description: str
    tags: list[str]
    aliases: list[str]
    is_animated: bool
    score: float
    keyword_score: float
    semantic_score: float
    rerank_score: float | None
    use_count: int


def normalize_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    normalized: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = str(item or "").strip()
        if not text:
            continue
        lowered = text.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        normalized.append(text)
    return normalized


def build_search_text(
    *,
    manual_description: str,
    auto_description: str,
    ocr_text: str,
    tags: list[str],
    aliases: list[str],
) -> str:
    parts: list[str] = []
    preferred = manual_description.strip() or auto_description.strip()
    if preferred:
        parts.append(preferred)
    if tags:
        parts.append(" ".join(tags))
    if aliases:
        parts.append(" ".join(aliases))
    return "\n".join(part for part in parts if part).strip()
