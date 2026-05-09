"""B 站下载数据模型。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True, frozen=True)
class VideoInfo:
    """视频基本信息。"""

    bvid: str
    title: str
    duration: int
    cover_url: str
    up_name: str
    desc: str
    cid: int

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
