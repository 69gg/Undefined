"""GitHub public API 客户端。"""

from __future__ import annotations

import re
from typing import Any

from Undefined.github.models import GitHubRepoInfo
from Undefined.github.parser import normalize_github_repo_id
from Undefined.skills.http_client import request_with_retry

_API_BASE_URL = "https://api.github.com"
_HEADERS = {
    "Accept": "application/vnd.github+json",
    "User-Agent": "Undefined-bot/3.x (https://github.com/69gg/Undefined)",
    "X-GitHub-Api-Version": "2022-11-28",
}
DEFAULT_REQUEST_TIMEOUT_SECONDS: float = 10.0
DEFAULT_REQUEST_RETRIES: int = 2


def _as_str(value: object) -> str:
    return str(value or "").strip()


def _as_int(value: object, default: int = 0) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if not isinstance(value, str):
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _as_optional_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if not isinstance(value, str):
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _topics(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(str(item).strip() for item in value if str(item).strip())


def _license_name(value: object) -> str:
    if not isinstance(value, dict):
        return ""
    return _as_str(value.get("spdx_id")) or _as_str(value.get("name"))


def _parse_contributor_count(link_header: str, payload: object) -> int | None:
    for part in link_header.split(","):
        if 'rel="last"' not in part:
            continue
        match = re.search(r"[?&]page=(\d+)", part)
        if match:
            return int(match.group(1))
    if isinstance(payload, list):
        return len(payload)
    return None


async def _fetch_contributor_count(
    repo_id: str,
    *,
    request_timeout: float,
    request_retries: int,
    context: dict[str, object] | None,
) -> int | None:
    response = await request_with_retry(
        "GET",
        f"{_API_BASE_URL}/repos/{repo_id}/contributors",
        params={"per_page": 1},
        headers=_HEADERS,
        timeout=request_timeout,
        follow_redirects=True,
        context=context,
        retries=request_retries,
        proxy_scope="github",
    )
    return _parse_contributor_count(response.headers.get("link", ""), response.json())


def _parse_repo_info(
    payload: dict[str, Any], contributor_count: int | None
) -> GitHubRepoInfo:
    owner = payload.get("owner")
    owner_data = owner if isinstance(owner, dict) else {}
    return GitHubRepoInfo(
        repo_id=_as_str(payload.get("full_name")),
        name=_as_str(payload.get("name")),
        full_name=_as_str(payload.get("full_name")),
        owner_login=_as_str(owner_data.get("login")),
        owner_avatar_url=_as_str(owner_data.get("avatar_url")),
        description=_as_str(payload.get("description")),
        html_url=_as_str(payload.get("html_url")),
        stars=_as_int(payload.get("stargazers_count")),
        forks=_as_int(payload.get("forks_count")),
        open_issues=_as_int(payload.get("open_issues_count")),
        watchers=_as_optional_int(payload.get("subscribers_count")),
        subscribers=_as_optional_int(payload.get("subscribers_count")),
        contributors=contributor_count,
        language=_as_str(payload.get("language")),
        license_name=_license_name(payload.get("license")),
        default_branch=_as_str(payload.get("default_branch")),
        topics=_topics(payload.get("topics")),
        created_at=_as_str(payload.get("created_at")),
        updated_at=_as_str(payload.get("updated_at")),
        pushed_at=_as_str(payload.get("pushed_at")),
        archived=bool(payload.get("archived")),
        fork=bool(payload.get("fork")),
    )


async def get_public_repo_info(
    repo_id: str,
    *,
    request_timeout: float = DEFAULT_REQUEST_TIMEOUT_SECONDS,
    request_retries: int = DEFAULT_REQUEST_RETRIES,
    context: dict[str, object] | None = None,
) -> GitHubRepoInfo:
    """获取 public GitHub 仓库信息。"""
    normalized = normalize_github_repo_id(repo_id)
    if normalized is None:
        raise ValueError(f"无法解析 GitHub 仓库标识: {repo_id}")

    response = await request_with_retry(
        "GET",
        f"{_API_BASE_URL}/repos/{normalized}",
        headers=_HEADERS,
        timeout=request_timeout,
        follow_redirects=True,
        context=context,
        retries=request_retries,
        proxy_scope="github",
    )
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("GitHub API 返回格式异常")
    if bool(payload.get("private")):
        raise ValueError(f"仅支持 public GitHub 仓库: {normalized}")

    contributor_count: int | None = None
    try:
        contributor_count = await _fetch_contributor_count(
            normalized,
            request_timeout=request_timeout,
            request_retries=request_retries,
            context=context,
        )
    except Exception:
        contributor_count = None

    info = _parse_repo_info(payload, contributor_count)
    if not info.repo_id:
        raise ValueError("GitHub API 返回缺少仓库 ID")
    return info
