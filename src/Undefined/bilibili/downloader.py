"""B 站视频下载适配层。"""

from __future__ import annotations

import asyncio
from functools import partial
import logging
from pathlib import Path
import uuid

from Undefined.bilibili.api_client import BilibiliApiClient
from Undefined.bilibili.download_core import QUALITY_MAP as QUALITY_MAP
from Undefined.bilibili.download_core import download_video as download_video_core
from Undefined.bilibili.models import VideoInfo as VideoInfo
from Undefined.utils.paths import DOWNLOAD_CACHE_DIR, ensure_dir

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT_SECONDS = 480.0

__all__ = [
    "QUALITY_MAP",
    "VideoInfo",
    "cleanup_file",
    "download_video",
    "get_video_info",
]


async def get_video_info(
    bvid: str,
    cookie: str = "",
    sessdata: str = "",
) -> VideoInfo:
    """获取视频基本信息。"""
    if not cookie and sessdata:
        cookie = sessdata

    return await asyncio.to_thread(partial(_get_video_info_sync, bvid, cookie=cookie))


def _get_video_info_sync(bvid: str, *, cookie: str = "") -> VideoInfo:
    with BilibiliApiClient(cookie=cookie, timeout=_DEFAULT_TIMEOUT_SECONDS) as client:
        return client.get_video_info(bvid)


def _download_video_sync(
    bvid: str,
    *,
    work_dir: Path,
    cookie: str,
    prefer_quality: int,
) -> tuple[Path, VideoInfo, int]:
    with BilibiliApiClient(cookie=cookie, timeout=_DEFAULT_TIMEOUT_SECONDS) as client:
        result = download_video_core(
            client,
            bvid=bvid,
            save_path=work_dir,
            prefer_quality=prefer_quality,
            overwrite=True,
        )
    return Path(result.path), result.video_info, int(result.quality)


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

    # 时长门禁：仅当调用方配置了 max_duration 时才预取元信息。
    # Duration gate: prefetch metadata only when max_duration is configured.
    if max_duration > 0:
        video_info = await get_video_info(bvid, cookie=cookie)
        if video_info.duration > max_duration:
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

    try:
        downloaded_path, video_info, actual_qn = await asyncio.to_thread(
            partial(
                _download_video_sync,
                bvid,
                work_dir=work_dir,
                cookie=cookie,
                prefer_quality=prefer_quality,
            )
        )

        logger.info(
            "[Bilibili] 下载完成: %s (%.1f MB, qn=%d)",
            bvid,
            downloaded_path.stat().st_size / 1024 / 1024,
            actual_qn,
        )
        return downloaded_path, video_info, actual_qn
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
