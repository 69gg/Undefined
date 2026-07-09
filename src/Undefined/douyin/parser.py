"""Douyin identifier parsing.

Supports short links, long video links, naked numeric aweme IDs and QQ JSON cards.
"""

from __future__ import annotations

import html
import json
import re
from typing import Any, Iterable
from urllib.parse import urlsplit

_DOUYIN_HOST_SUFFIXES = ("douyin.com", "iesdouyin.com")
_DOUYIN_URL_PATTERN = re.compile(
    r"(?:https?://)?(?:(?:www|v|www\.ies|m)\.)?(?:douyin|iesdouyin)\.com/[^\s<>\"]+",
    re.IGNORECASE,
)
_AWEME_ID_PATTERN = re.compile(r"(?<!\d)(\d{16,25})(?!\d)")


def _strip_trailing_punctuation(value: str) -> str:
    return value.rstrip(".,;:!?，。；：！？）)]】》\"'")


def _normalize_url(url: str) -> str:
    text = _strip_trailing_punctuation(str(url or "").strip())
    if not text:
        return ""
    lowered = text.lower()
    if lowered.startswith("http://"):
        text = f"https://{text[7:]}"
    elif not lowered.startswith("https://"):
        text = f"https://{text}"
    return text


def _is_douyin_url(url: str) -> bool:
    try:
        host = urlsplit(_normalize_url(url)).netloc.lower()
    except ValueError:
        return False
    return any(
        host == suffix or host.endswith(f".{suffix}")
        for suffix in _DOUYIN_HOST_SUFFIXES
    )


def extract_douyin_ids(text: str) -> list[str]:
    """Extract Douyin URLs and naked aweme IDs from text, preserving order."""

    items: list[str] = []
    seen: set[str] = set()
    url_spans: list[tuple[int, int]] = []

    for match in _DOUYIN_URL_PATTERN.finditer(str(text or "")):
        url = _normalize_url(match.group(0))
        if not url or not _is_douyin_url(url):
            continue
        url_spans.append(match.span())
        if url not in seen:
            seen.add(url)
            items.append(url)

    for match in _AWEME_ID_PATTERN.finditer(str(text or "")):
        start = match.start()
        if any(span_start <= start < span_end for span_start, span_end in url_spans):
            continue
        aweme_id = match.group(1)
        if aweme_id not in seen:
            seen.add(aweme_id)
            items.append(aweme_id)

    return items


def _iter_json_strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
        return
    if isinstance(value, dict):
        for item in value.values():
            yield from _iter_json_strings(item)
        return
    if isinstance(value, list):
        for item in value:
            yield from _iter_json_strings(item)


def extract_from_json_message(segments: list[dict[str, Any]]) -> list[str]:
    """Extract Douyin identifiers from QQ JSON card message segments."""

    items: list[str] = []
    seen: set[str] = set()

    for segment in segments:
        if segment.get("type") != "json":
            continue
        raw_data = segment.get("data", {}).get("data", "")
        if not raw_data:
            continue
        raw_text = html.unescape(str(raw_data))
        try:
            payload = json.loads(raw_text)
        except (json.JSONDecodeError, TypeError):
            for item in extract_douyin_ids(raw_text):
                if item not in seen:
                    seen.add(item)
                    items.append(item)
            continue

        for value in _iter_json_strings(payload):
            for item in extract_douyin_ids(value):
                if item not in seen:
                    seen.add(item)
                    items.append(item)

    return items


def canonical_share_url(identifier: str) -> str | None:
    """Build a canonical share-page URL for a URL or naked aweme ID."""

    text = str(identifier or "").strip()
    if not text:
        return None

    aweme_match = _AWEME_ID_PATTERN.fullmatch(text)
    if aweme_match:
        return f"https://www.iesdouyin.com/share/video/{aweme_match.group(1)}/"

    url = _normalize_url(text)
    if not _is_douyin_url(url):
        return None

    path = urlsplit(url).path
    match = re.search(r"/(?:share/)?video/(\d{16,25})(?:/|$)", path)
    if match:
        return f"https://www.iesdouyin.com/share/video/{match.group(1)}/"

    return url


def normalize_aweme_id(identifier: str) -> str | None:
    """Return aweme ID if it is directly available in the identifier."""

    text = str(identifier or "").strip()
    if not text:
        return None
    match = _AWEME_ID_PATTERN.search(text)
    return match.group(1) if match else None
