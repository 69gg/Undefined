"""GitHub 仓库标识解析。"""

from __future__ import annotations

import html
import json
import logging
import re
from typing import Any
from urllib.parse import unquote, urlparse

logger = logging.getLogger(__name__)

_URL_HOSTS = {"github.com", "www.github.com"}
_HTTP_URL_REGEX = re.compile(r"https?://(?:www\.)?github\.com/[^\s<>()]+", re.I)
_SCHEMELESS_URL_REGEX = re.compile(
    r"(?<![\w@.-])(?:www\.)?github\.com/[^\s<>()]+",
    re.I,
)
_SSH_URL_REGEX = re.compile(
    r"git@github\.com:([A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?)/([^\s<>()]+)",
    re.I,
)
_BARE_REPO_REGEX = re.compile(
    r"(?<![\w@./:-])([A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?/[A-Za-z0-9._-]{1,100})(?![\w./-])"
)
_OWNER_REGEX = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")
_REPO_REGEX = re.compile(r"^[A-Za-z0-9._-]{1,100}$")
_COMMON_PATH_LIKE_BARE_OWNERS = {
    "api",
    "app",
    "apps",
    "asset",
    "assets",
    "bin",
    "build",
    "cache",
    "code",
    "config",
    "configs",
    "data",
    "dist",
    "doc",
    "docs",
    "example",
    "examples",
    "img",
    "image",
    "images",
    "lib",
    "log",
    "logs",
    "node_modules",
    "public",
    "res",
    "resource",
    "resources",
    "script",
    "scripts",
    "src",
    "static",
    "test",
    "tests",
    "tmp",
    "vendor",
}


def _strip_wrapper_chars(value: str) -> str:
    stripped = value.strip()
    while stripped and stripped[-1] in ".,;:!?)>]}\"'":
        stripped = stripped[:-1].rstrip()
    while stripped and stripped[0] in "(<[{\"'":
        stripped = stripped[1:].lstrip()
    return stripped


def _normalize_owner_repo(owner: str, repo: str, *, bare: bool = False) -> str | None:
    normalized_owner = _strip_wrapper_chars(html.unescape(owner)).strip()
    normalized_repo = _strip_wrapper_chars(html.unescape(repo)).strip()
    normalized_repo = normalized_repo.split("?", 1)[0].split("#", 1)[0]
    if normalized_repo.lower().endswith(".git"):
        normalized_repo = normalized_repo[:-4]
    normalized_repo = normalized_repo.strip("/")
    if not normalized_owner or not normalized_repo:
        return None
    if not _OWNER_REGEX.fullmatch(normalized_owner):
        return None
    if normalized_repo in {".", ".."}:
        return None
    if not _REPO_REGEX.fullmatch(normalized_repo):
        return None
    if bare:
        if normalized_owner.isdigit() and normalized_repo.isdigit():
            return None
        if normalized_owner.lower() in _COMMON_PATH_LIKE_BARE_OWNERS:
            return None
    return f"{normalized_owner}/{normalized_repo}"


def normalize_github_repo_id(identifier: str) -> str | None:
    """将 GitHub URL、SSH URL 或 owner/repo 文本标准化为仓库 ID。"""
    raw = _strip_wrapper_chars(html.unescape(identifier))
    if not raw:
        return None

    ssh_match = _SSH_URL_REGEX.search(raw)
    if ssh_match:
        return _normalize_owner_repo(ssh_match.group(1), ssh_match.group(2))

    parse_target = raw
    if re.match(r"^(?:www\.)?github\.com/", parse_target, re.I):
        parse_target = f"https://{parse_target}"
    parsed = urlparse(parse_target)
    hostname = parsed.hostname.lower() if parsed.hostname else ""
    if hostname in _URL_HOSTS:
        path = unquote(parsed.path or "").strip("/")
        parts = [part for part in path.split("/") if part]
        if len(parts) >= 2:
            return _normalize_owner_repo(parts[0], parts[1])
        return None

    bare_match = _BARE_REPO_REGEX.fullmatch(raw)
    if bare_match:
        owner, repo = bare_match.group(1).split("/", 1)
        return _normalize_owner_repo(owner, repo, bare=True)
    return None


def _append_candidate(
    candidate: str,
    *,
    results: list[str],
    seen: set[str],
) -> None:
    repo_id = normalize_github_repo_id(candidate)
    if repo_id is None or repo_id.lower() in seen:
        return
    seen.add(repo_id.lower())
    results.append(repo_id)


def extract_github_repo_ids(text: str) -> list[str]:
    """从纯文本中提取 GitHub 仓库 ID。"""
    results: list[str] = []
    seen: set[str] = set()

    for match in _HTTP_URL_REGEX.finditer(text):
        _append_candidate(match.group(0), results=results, seen=seen)

    for match in _SCHEMELESS_URL_REGEX.finditer(text):
        _append_candidate(match.group(0), results=results, seen=seen)

    for match in _SSH_URL_REGEX.finditer(text):
        _append_candidate(match.group(0), results=results, seen=seen)

    for match in _BARE_REPO_REGEX.finditer(text):
        _append_candidate(match.group(1), results=results, seen=seen)

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
    """从 QQ JSON 消息段中提取 GitHub 仓库 ID。"""
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
            logger.debug("[GitHub] JSON 消息解析失败，跳过", exc_info=True)
            continue

        for item in _collect_json_strings(payload):
            for repo_id in extract_github_repo_ids(item):
                if repo_id.lower() in seen:
                    continue
                seen.add(repo_id.lower())
                results.append(repo_id)

    return results
