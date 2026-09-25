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


@dataclass(slots=True, frozen=True)
class OpusStats:
    """图文互动统计。"""

    view: int = 0
    like: int = 0
    comment: int = 0
    repost: int = 0
    coin: int = 0
    favorite: int = 0


@dataclass(slots=True, frozen=True)
class OpusAuthor:
    """图文作者信息。"""

    mid: int = 0
    name: str = ""
    avatar_url: str = ""


@dataclass(slots=True, frozen=True)
class TextBlock:
    """图文段落中的纯文本。"""

    text: str


@dataclass(slots=True, frozen=True)
class ImageBlock:
    """图文段落中的图片组。"""

    urls: tuple[str, ...]


@dataclass(slots=True, frozen=True)
class VideoCardBlock:
    """指向投稿视频的卡片段落。"""

    bvid: str = ""
    title: str = ""
    cover_url: str = ""
    jump_url: str = ""


@dataclass(slots=True, frozen=True)
class OpusCardBlock:
    """指向另一篇图文的卡片段落。"""

    opus_id: str = ""
    title: str = ""
    cover_url: str = ""
    jump_url: str = ""


@dataclass(slots=True, frozen=True)
class LinkCardBlock:
    """其它类型的卡片段落（商品 / 直播 / 投票 / 通用链接等）。"""

    title: str = ""
    jump_url: str = ""
    cover_url: str = ""


OpusBlock = TextBlock | ImageBlock | VideoCardBlock | OpusCardBlock | LinkCardBlock


@dataclass(slots=True, frozen=True)
class OpusInfo:
    """图文（opus / 动态）基本信息。"""

    opus_id: str
    title: str
    blocks: tuple[OpusBlock, ...]
    author: OpusAuthor = OpusAuthor()
    stats: OpusStats = OpusStats()
    pub_ts: int = 0
    cover_url: str = ""
    dynamic_type_id: str = ""
    is_forward: bool = False
    forward_origin: OpusAuthor | None = None

    @property
    def url(self) -> str:
        """标准图文链接。"""
        return f"https://www.bilibili.com/opus/{self.opus_id}"

    @property
    def images(self) -> tuple[str, ...]:
        """按顺序收集全部图片 URL。"""
        urls: list[str] = []
        for block in self.blocks:
            if isinstance(block, ImageBlock):
                urls.extend(block.urls)
        return tuple(urls)
