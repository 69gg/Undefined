"""arXiv 标识解析。"""

from __future__ import annotations

import html
import json
import logging
import re
from typing import Any
from urllib.parse import unquote, urlparse

logger = logging.getLogger(__name__)

_URL_HOSTS = {"arxiv.org", "www.arxiv.org", "export.arxiv.org"}
_URL_REGEX = re.compile(r"https?://(?:www\.|export\.)?arxiv\.org/[^\s<>()]+", re.I)
_ARXIV_PREFIX_REGEX = re.compile(
    r"\barxiv\s*:\s*([A-Za-z0-9.\-\/]+(?:v\d+)?)",
    re.I,
)
_NEW_ID_REGEX = re.compile(r"\b\d{4}\.\d{4,5}(?:v\d+)?\b")
_OLD_ID_REGEX = re.compile(r"\b[a-z][a-z.\-]+/\d{7}(?:v\d+)?\b", re.I)
_ARXIV_KEYWORD_REGEX = re.compile(r"\barxiv\b", re.I)


def _strip_wrapper_chars(value: str) -> str:
    stripped = value.strip()
    while stripped and stripped[-1] in ".,;:!?)>]}'\"":
        stripped = stripped[:-1].rstrip()
    while stripped and stripped[0] in "(<[{'\"":
        stripped = stripped[1:].lstrip()
    return stripped


def _normalize_candidate(candidate: str) -> str | None:
    normalized = _strip_wrapper_chars(html.unescape(candidate).strip())
    if not normalized:
        return None
    if _NEW_ID_REGEX.fullmatch(normalized):
        return normalized
    if _OLD_ID_REGEX.fullmatch(normalized):
        return normalized
    return None


def normalize_arxiv_id(identifier: str) -> str | None:
    """将 URL 或文本中的 arXiv 标识标准化。"""
    raw = html.unescape(identifier).strip()
    if not raw:
        return None

    prefix_match = _ARXIV_PREFIX_REGEX.search(raw)
    if prefix_match:
        return _normalize_candidate(prefix_match.group(1))

    parsed = urlparse(raw)
    hostname = parsed.hostname.lower() if parsed.hostname else ""
    if hostname in _URL_HOSTS:
        path = unquote(parsed.path or "").strip()
        if path.startswith("/abs/"):
            return _normalize_candidate(path.removeprefix("/abs/"))
        if path.startswith("/pdf/"):
            candidate = path.removeprefix("/pdf/")
            if candidate.lower().endswith(".pdf"):
                candidate = candidate[:-4]
            return _normalize_candidate(candidate)

    return _normalize_candidate(raw)


def _append_candidate(
    candidate: str,
    *,
    results: list[str],
    seen: set[str],
) -> None:
    normalized = normalize_arxiv_id(candidate)
    if normalized is None or normalized in seen:
        return
    seen.add(normalized)
    results.append(normalized)


def extract_arxiv_ids(text: str) -> list[str]:
    """从纯文本中提取 arXiv 标识。"""
    results: list[str] = []
    seen: set[str] = set()

    for match in _URL_REGEX.finditer(text):
        _append_candidate(match.group(0), results=results, seen=seen)

    for match in _ARXIV_PREFIX_REGEX.finditer(text):
        _append_candidate(match.group(1), results=results, seen=seen)

    if _ARXIV_KEYWORD_REGEX.search(text):
        for match in _NEW_ID_REGEX.finditer(text):
            _append_candidate(match.group(0), results=results, seen=seen)

    return results


def _collect_json_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        strings: list[str] = []
        for item in value:
            strings.extend(_collect_json_strings(item))
        return strings
    if isinstance(value, dict):
        strings = []
        for item in value.values():
            strings.extend(_collect_json_strings(item))
        return strings
    return []


def extract_from_json_message(segments: list[dict[str, Any]]) -> list[str]:
    """从 QQ JSON 消息段中提取 arXiv 标识。"""
    results: list[str] = []
    seen: set[str] = set()

    for segment in segments:
        if segment.get("type") != "json":
            continue

        raw_data = segment.get("data", {}).get("data", "")
        if not raw_data:
            continue

        try:
            payload = json.loads(html.unescape(raw_data))
        except (TypeError, json.JSONDecodeError):
            logger.debug("[arXiv] JSON 消息解析失败，跳过", exc_info=True)
            continue

        for item in _collect_json_strings(payload):
            for paper_id in extract_arxiv_ids(item):
                if paper_id in seen:
                    continue
                seen.add(paper_id)
                results.append(paper_id)

    return results
