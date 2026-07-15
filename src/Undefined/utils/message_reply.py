"""Structured quoted-message context shared by transports and prompts."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any


_INLINE_ATTACHMENT_RE = re.compile(
    r"<attachment\s+uid=(?P<quote>[\"'])(?P<uid>[^\"']+)(?P=quote)\s*/?>",
    re.IGNORECASE,
)
_HISTORY_ATTACHMENT_RE = re.compile(
    r"\[(?P<label>图片|文件|视频|语音|音频|附件)\s+"
    r"uid=(?P<uid>[^\s\]]+)(?:\s+name=[^\]]+)?\]",
    re.IGNORECASE,
)
_MEDIA_LABELS: dict[str, str] = {
    "image": "图片",
    "pic": "图片",
    "file": "文件",
    "video": "视频",
    "voice": "语音",
    "record": "语音",
    "audio": "音频",
}


def _normalize_attachment(item: object) -> dict[str, str] | None:
    if not isinstance(item, Mapping):
        return None
    uid = str(item.get("uid", "") or "").strip()
    if not uid:
        return None
    kind = str(item.get("kind") or item.get("media_type") or "file").strip()
    media_type = str(item.get("media_type") or kind or "file").strip()
    normalized: dict[str, str] = {
        "uid": uid,
        "kind": kind,
        "media_type": media_type,
        "display_name": str(item.get("display_name", "") or "").strip(),
    }
    for key in ("source_kind", "source_ref", "semantic_kind", "description"):
        value = str(item.get(key, "") or "").strip()
        if value:
            normalized[key] = value
    return normalized


@dataclass(frozen=True, slots=True)
class ReplyContext:
    """A quoted message rendered as read-only context beside the current body."""

    title: str = ""
    message_id: str = ""
    text: str = ""
    attachments: tuple[dict[str, str], ...] = ()

    @property
    def is_empty(self) -> bool:
        return not (self.title or self.message_id or self.text or self.attachments)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "title": self.title,
            "message_id": self.message_id,
            "message": self.text,
        }
        if self.attachments:
            payload["attachments"] = [dict(item) for item in self.attachments]
        return payload

    @classmethod
    def from_mapping(cls, value: object) -> ReplyContext | None:
        if not isinstance(value, Mapping):
            return None
        raw_attachments = value.get("attachments")
        attachments: list[dict[str, str]] = []
        if isinstance(raw_attachments, Sequence) and not isinstance(
            raw_attachments, (str, bytes)
        ):
            for item in raw_attachments:
                normalized = _normalize_attachment(item)
                if normalized is not None:
                    attachments.append(normalized)
        context = cls(
            title=str(value.get("title", "") or "").strip(),
            message_id=str(value.get("message_id", "") or "").strip(),
            text=str(value.get("message", value.get("text", "")) or "").strip(),
            attachments=tuple(attachments),
        )
        return None if context.is_empty else context


def build_safe_reply_preview(
    text: str,
    attachments: Sequence[Mapping[str, str]],
) -> str:
    """Build a wire-safe quote preview without local paths or attachment UIDs."""

    cleaned = _INLINE_ATTACHMENT_RE.sub("", str(text or ""))
    cleaned = _HISTORY_ATTACHMENT_RE.sub("", cleaned)
    cleaned_lines = [
        line.rstrip()
        for line in cleaned.splitlines()
        if line.strip() not in {"附件:", "附件："}
    ]
    cleaned = "\n".join(cleaned_lines).strip()

    media_parts: list[str] = []
    for item in attachments:
        media_type = str(item.get("media_type") or item.get("kind") or "file")
        label = _MEDIA_LABELS.get(media_type.strip().lower(), "附件")
        raw_name = str(item.get("display_name", "") or "").strip()
        name = Path(raw_name.replace("\\", "/")).name if raw_name else ""
        media_parts.append(f"[{label}: {name}]" if name else f"[{label}]")

    parts = [part for part in (cleaned, " ".join(media_parts)) if part]
    return "\n".join(parts) or "[消息]"


def format_markdown_reply(context: ReplyContext, body: str) -> str:
    """Render a deterministic Markdown fallback for a native quoted reply."""

    title = " ".join(context.title.split()) or "消息"
    preview = build_safe_reply_preview(context.text, context.attachments)
    quote_lines = [f"> **引用 {title}**"]
    quote_lines.extend(f"> {line}" if line else ">" for line in preview.splitlines())
    quoted = "\n".join(quote_lines)
    return f"{quoted}\n\n{body}" if body else quoted


__all__ = [
    "ReplyContext",
    "build_safe_reply_preview",
    "format_markdown_reply",
]
