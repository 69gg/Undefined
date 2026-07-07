"""Douyin video data models."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True, frozen=True)
class DouyinVideoInfo:
    """Basic Douyin video metadata parsed from the share page."""

    aweme_id: str
    title: str
    author_name: str
    desc: str
    cover_url: str
    duration: int
    share_url: str
    play_token: str


@dataclass(slots=True, frozen=True)
class DouyinQualityProbe:
    """A playable quality candidate discovered through the play endpoint."""

    ratio: str
    play_url: str
    size_bytes: int | None


@dataclass(slots=True, frozen=True)
class DouyinDownloadResult:
    """Downloaded Douyin video file and selected metadata."""

    path: Path
    size_bytes: int
    ratio: str
    video_info: DouyinVideoInfo
