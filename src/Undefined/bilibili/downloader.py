"""B 站视频下载

通过 B 站 API 获取视频信息，下载 DASH 音视频流并用 ffmpeg 合并。
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from Undefined.utils.paths import DOWNLOAD_CACHE_DIR, ensure_dir

logger = logging.getLogger(__name__)

_BILIBILI_API_VIEW = "https://api.bilibili.com/x/web-interface/view"
_BILIBILI_API_PLAYURL = "https://api.bilibili.com/x/player/playurl"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.bilibili.com",
}

# 清晰度映射
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
    """视频基本信息"""

    bvid: str
    title: str
    duration: int  # 秒
    cover_url: str  # 封面图 URL
    up_name: str  # UP 主名
    desc: str  # 简介


async def get_video_info(bvid: str, sessdata: str = "") -> VideoInfo:
    """获取视频基本信息。

    Raises:
        ValueError: API 返回错误或视频不存在。
        httpx.HTTPError: 网络请求失败。
    """
    cookies: dict[str, str] = {}
    if sessdata:
        cookies["SESSDATA"] = sessdata

    async with httpx.AsyncClient(
        headers=_HEADERS, cookies=cookies, timeout=15, follow_redirects=True
    ) as client:
        resp = await client.get(_BILIBILI_API_VIEW, params={"bvid": bvid})
        resp.raise_for_status()
        data: dict[str, Any] = resp.json()

    if data.get("code") != 0:
        msg = data.get("message", "未知错误")
        raise ValueError(f"获取视频信息失败: {msg} (bvid={bvid})")

    info = data["data"]
    owner = info.get("owner", {})
    return VideoInfo(
        bvid=bvid,
        title=info.get("title", ""),
        duration=info.get("duration", 0),
        cover_url=info.get("pic", ""),
        up_name=owner.get("name", ""),
        desc=info.get("desc", ""),
    )


def _select_quality(available_qualities: list[int], prefer: int) -> int:
    """选择最合适的清晰度。

    优先选择 prefer；不可用时选最接近且不超过的；都超过则选最低。
    """
    if not available_qualities:
        return prefer
    if prefer in available_qualities:
        return prefer
    # 不超过 prefer 的最高清晰度
    lower = [q for q in available_qualities if q <= prefer]
    if lower:
        return max(lower)
    # 所有都比 prefer 高，选最低
    return min(available_qualities)


async def _download_stream(
    client: httpx.AsyncClient,
    url: str,
    dest: Path,
) -> None:
    """下载单个流到文件。"""
    async with client.stream("GET", url, headers=_HEADERS) as resp:
        resp.raise_for_status()
        with open(dest, "wb") as f:
            async for chunk in resp.aiter_bytes(chunk_size=1024 * 64):
                f.write(chunk)


async def _merge_av(video_path: Path, audio_path: Path, output_path: Path) -> None:
    """用 ffmpeg 合并音视频流。"""
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(video_path),
        "-i",
        str(audio_path),
        "-c:v",
        "copy",
        "-c:a",
        "copy",
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg 合并失败: {stderr.decode(errors='replace')[:500]}")


async def download_video(
    bvid: str,
    sessdata: str = "",
    prefer_quality: int = 80,
    max_duration: int = 0,
    output_dir: Path | None = None,
) -> tuple[Path | None, VideoInfo, int]:
    """下载 B 站视频。

    Args:
        bvid: BV 号。
        sessdata: B 站 SESSDATA cookie。
        prefer_quality: 首选清晰度 qn（80=1080P）。
        max_duration: 最大时长限制（秒），0 表示不限。
        output_dir: 输出目录，默认 DOWNLOAD_CACHE_DIR。

    Returns:
        (视频文件路径 | None, 视频信息, 实际清晰度 qn)。
        如果超时长限制，视频路径为 None。
    """
    video_info = await get_video_info(bvid, sessdata)

    # 时长检查
    if max_duration > 0 and video_info.duration > max_duration:
        logger.info(
            "[Bilibili] 视频时长 %ds 超过限制 %ds，跳过下载: %s",
            video_info.duration,
            max_duration,
            bvid,
        )
        return None, video_info, 0

    # 获取播放地址
    cookies: dict[str, str] = {}
    if sessdata:
        cookies["SESSDATA"] = sessdata

    async with httpx.AsyncClient(
        headers=_HEADERS, cookies=cookies, timeout=15, follow_redirects=True
    ) as client:
        resp = await client.get(
            _BILIBILI_API_PLAYURL,
            params={
                "bvid": bvid,
                "cid": await _get_cid(bvid, sessdata),
                "fnval": 16,  # DASH 格式
                "fourk": 1,
            },
        )
        resp.raise_for_status()
        data: dict[str, Any] = resp.json()

    if data.get("code") != 0:
        raise ValueError(f"获取播放地址失败: {data.get('message', '未知错误')}")

    dash = data["data"].get("dash")
    if not dash:
        raise ValueError("该视频不支持 DASH 格式下载")

    # 选择视频流
    video_streams: list[dict[str, Any]] = dash.get("video", [])
    audio_streams: list[dict[str, Any]] = dash.get("audio", []) or []

    if not video_streams:
        raise ValueError("未找到可用的视频流")

    available_qns = list({v["id"] for v in video_streams})
    actual_qn = _select_quality(available_qns, prefer_quality)

    # 选择该清晰度下编码最优的视频流
    target_videos = [v for v in video_streams if v["id"] == actual_qn]
    if not target_videos:
        target_videos = video_streams
        actual_qn = target_videos[0]["id"]
    video_stream = target_videos[0]

    # 选择最高质量音频流
    audio_stream = audio_streams[0] if audio_streams else None

    # 准备临时目录
    if output_dir is None:
        output_dir = DOWNLOAD_CACHE_DIR
    work_dir = ensure_dir(output_dir / uuid.uuid4().hex)

    video_tmp = work_dir / "video.m4s"
    audio_tmp = work_dir / "audio.m4s"
    output_file = work_dir / f"{bvid}.mp4"

    try:
        video_url = video_stream.get("baseUrl") or video_stream.get("base_url", "")
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(connect=15, read=120, write=15, pool=15),
            follow_redirects=True,
        ) as client:
            # 下载视频流
            logger.info(
                "[Bilibili] 开始下载视频流 %s (qn=%d %s)",
                bvid,
                actual_qn,
                QUALITY_MAP.get(actual_qn, "未知"),
            )
            await _download_stream(client, video_url, video_tmp)

            # 下载音频流
            if audio_stream:
                audio_url = audio_stream.get("baseUrl") or audio_stream.get(
                    "base_url", ""
                )
                logger.info("[Bilibili] 开始下载音频流 %s", bvid)
                await _download_stream(client, audio_url, audio_tmp)

        # 合并
        if audio_stream and audio_tmp.exists():
            logger.info("[Bilibili] ffmpeg 合并音视频 %s", bvid)
            await _merge_av(video_tmp, audio_tmp, output_file)
        else:
            # 无音频流，直接重命名视频
            video_tmp.rename(output_file)

        # 清理临时 m4s 文件
        for tmp in (video_tmp, audio_tmp):
            if tmp.exists():
                tmp.unlink()

        logger.info(
            "[Bilibili] 下载完成: %s (%.1f MB, qn=%d)",
            bvid,
            output_file.stat().st_size / 1024 / 1024,
            actual_qn,
        )
        return output_file, video_info, actual_qn

    except Exception:
        # 出错时清理工作目录
        _cleanup_dir(work_dir)
        raise


async def _get_cid(bvid: str, sessdata: str = "") -> int:
    """获取视频的 cid。"""
    cookies: dict[str, str] = {}
    if sessdata:
        cookies["SESSDATA"] = sessdata

    async with httpx.AsyncClient(
        headers=_HEADERS, cookies=cookies, timeout=15, follow_redirects=True
    ) as client:
        resp = await client.get(_BILIBILI_API_VIEW, params={"bvid": bvid})
        resp.raise_for_status()
        data: dict[str, Any] = resp.json()

    if data.get("code") != 0:
        raise ValueError(f"获取 cid 失败: {data.get('message', '未知错误')}")

    pages = data["data"].get("pages", [])
    if not pages:
        raise ValueError(f"视频无分P信息: {bvid}")
    return int(pages[0]["cid"])


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
