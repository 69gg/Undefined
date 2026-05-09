"""B 站下载数据模型。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True, frozen=True)
class VideoStats:
    """视频互动统计。"""

    view: int = 0
    danmaku: int = 0
    reply: int = 0
    favorite: int = 0
    coin: int = 0
    share: int = 0
    like: int = 0


@dataclass(slots=True, frozen=True)
class VideoInfo:
    """视频基本信息。"""

    bvid: str
    aid: int
    title: str
    duration: int
    cover_url: str
    up_name: str
    desc: str
    cid: int
    page_duration: int
    stats: VideoStats

    @property
    def url(self) -> str:
        """标准视频链接。"""
        return f"https://www.bilibili.com/video/{self.bvid}"


@dataclass(slots=True, frozen=True)
class DownloadResult:
    """视频下载结果。"""

    path: Path
    size_bytes: int
    quality: int
    quality_label: str
    video_info: VideoInfo


@dataclass(slots=True, frozen=True)
class DanmakuItem:
    """单条弹幕。"""

    progress_ms: int
    content: str
    dmid: str = ""
    mode: int = 0
    pool: int = 0
    ctime: int = 0
    mid_hash: str = ""
    color: int = 0
    weight: int = 0
