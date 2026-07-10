"""GitHub 仓库信息模型。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GitHubRepoInfo:
    """GitHub public 仓库信息。"""

    repo_id: str
    name: str
    full_name: str
    owner_login: str
    owner_avatar_url: str
    description: str
    html_url: str
    stars: int
    forks: int
    open_issues: int
    watchers: int | None
    subscribers: int | None
    contributors: int | None
    language: str
    license_name: str
    default_branch: str
    topics: tuple[str, ...]
    created_at: str
    updated_at: str
    pushed_at: str
    archived: bool
    fork: bool


@dataclass(frozen=True)
class GitHubReleaseInfo:
    """GitHub Release metadata used by the WebUI update flow."""

    tag_name: str
    name: str
    html_url: str
    published_at: str
    target_commitish: str
    draft: bool
    prerelease: bool
