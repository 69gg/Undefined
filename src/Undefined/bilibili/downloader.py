"""B 站视频下载适配层。

使用 `oh_my_bilibili` 提供的视频信息获取和下载能力，
对外保持本项目原有接口与返回结构不变。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from functools import partial
import logging
from pathlib import Path
import uuid
from typing import Any, Protocol, cast

from Undefined.utils.paths import DOWNLOAD_CACHE_DIR, ensure_dir

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT_SECONDS = 480.0

# 清晰度映射（兼容发送层展示逻辑）
QUALITY_MAP: dict[int, str] = {
    127: "8K",
    126: "杜比视界",
    125: "HDR",
    120: "4K",
    116: "1080P60",
    112: "1080P+",
    80: "1080P",
    64: "720P",
    32: "480P",
    16: "360P",
}


@dataclass
class VideoInfo:
    """视频基本信息。"""

    bvid: str
    title: str
    duration: int  # 秒
    cover_url: str  # 封面图 URL
    up_name: str  # UP 主名
    desc: str  # 简介
    cid: int  # 视频 cid


class _OmbVideoInfo(Protocol):
    """`oh_my_bilibili.models.VideoInfo` 最小结构约束。"""

    bvid: str
    title: str
    duration: int
    cover_url: str
    up_name: str
    desc: str
    cid: int


class _OmbDownloadResult(Protocol):
    """`oh_my_bilibili.models.DownloadResult` 最小结构约束。"""

    path: Path
    quality: int
    video_info: _OmbVideoInfo


def _require_omb() -> tuple[Any, Any]:
    """按需导入 oh_my_bilibili，缺失时给出明确错误。"""
    try:
        from oh_my_bilibili import download, get_video_info
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "未安装依赖 oh-my-bilibili。请先执行 `uv add oh-my-bilibili` 或 `uv sync`。"
        ) from exc
    return get_video_info, download


def _map_video_info(raw: _OmbVideoInfo) -> VideoInfo:
    """将 oh_my_bilibili 的 VideoInfo 映射为项目内部结构。"""
    return VideoInfo(
        bvid=str(raw.bvid),
        title=str(raw.title),
        duration=int(raw.duration),
        cover_url=str(raw.cover_url),
        up_name=str(raw.up_name),
        desc=str(raw.desc),
        cid=int(raw.cid),
    )


async def get_video_info(
    bvid: str,
    cookie: str = "",
    sessdata: str = "",
) -> VideoInfo:
    """获取视频基本信息。"""
    if not cookie and sessdata:
        cookie = sessdata

    omb_get_video_info, _ = _require_omb()
    raw = cast(
        _OmbVideoInfo,
        await asyncio.to_thread(
            partial(
                omb_get_video_info,
                bvid,
                cookie=cookie,
                timeout=_DEFAULT_TIMEOUT_SECONDS,
            )
        ),
    )
    return _map_video_info(raw)


async def download_video(
    bvid: str,
    cookie: str = "",
    prefer_quality: int = 80,
    max_duration: int = 0,
    output_dir: Path | None = None,
    sessdata: str = "",
) -> tuple[Path | None, VideoInfo, int]:
    """下载 B 站视频。

    Returns:
        (视频文件路径 | None, 视频信息, 实际清晰度 qn)。
        如果超时长限制，视频路径为 None。
    """
    if not cookie and sessdata:
        cookie = sessdata

    video_info = await get_video_info(bvid, cookie=cookie)

    # 时长检查
    if max_duration > 0 and video_info.duration > max_duration:
        logger.info(
            "[Bilibili] 视频时长 %ds 超过限制 %ds，跳过下载: %s",
            video_info.duration,
            max_duration,
            bvid,
        )
        return None, video_info, 0

    if output_dir is None:
        output_dir = DOWNLOAD_CACHE_DIR
    work_dir = ensure_dir(output_dir / uuid.uuid4().hex)

    _, omb_download = _require_omb()

    try:
        result = cast(
            _OmbDownloadResult,
            await asyncio.to_thread(
                partial(
                    omb_download,
                    bvid,
                    save_path=work_dir,
                    cookie=cookie,
                    prefer_quality=prefer_quality,
                    timeout=_DEFAULT_TIMEOUT_SECONDS,
                    overwrite=True,
                )
            ),
        )
        downloaded_path = Path(result.path)
        mapped_info = _map_video_info(result.video_info)
        actual_qn = int(result.quality)

        logger.info(
            "[Bilibili] 下载完成: %s (%.1f MB, qn=%d)",
            bvid,
            downloaded_path.stat().st_size / 1024 / 1024,
            actual_qn,
        )
        return downloaded_path, mapped_info, actual_qn
    except Exception:
        _cleanup_dir(work_dir)
        raise


def _cleanup_dir(path: Path) -> None:
    """递归删除目录及其内容。"""
    if not path.exists():
        return
    try:
        for item in path.iterdir():
            if item.is_file():
                item.unlink()
            elif item.is_dir():
                _cleanup_dir(item)
        path.rmdir()
    except Exception as exc:
        logger.warning("[Bilibili] 清理临时目录失败 %s: %s", path, exc)


def cleanup_file(path: Path) -> None:
    """清理单个文件及其所在的工作目录（如果为空）。"""
    if not path.exists():
        return
    try:
        parent = path.parent
        path.unlink()
        # 如果父目录为空，一并清理
        if parent.exists() and not any(parent.iterdir()):
            parent.rmdir()
    except Exception as exc:
        logger.warning("[Bilibili] 清理文件失败 %s: %s", path, exc)
