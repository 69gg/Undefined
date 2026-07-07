"""Douyin mp4 downloader."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
import shutil
from typing import Any
from urllib.parse import urlencode
import uuid

import aiofiles
import httpx

from Undefined.douyin.client import get_video_info
from Undefined.douyin.models import (
    DouyinDownloadResult,
    DouyinQualityProbe,
    DouyinVideoInfo,
)
from Undefined.skills.http_config import build_httpx_client_kwargs, get_request_timeout
from Undefined.utils.paths import DOWNLOAD_CACHE_DIR, ensure_dir

logger = logging.getLogger(__name__)

DEFAULT_RATIOS: tuple[str, ...] = ("1080p", "720p", "540p", "360p")
_PLAY_ENDPOINT = "https://aweme.snssdk.com/aweme/v1/play/"
_DOUYIN_DOWNLOAD_DIR = DOWNLOAD_CACHE_DIR / "douyin"
_PROBE_TIMEOUT_SECONDS = 30.0
_DOWNLOAD_CHUNK_SIZE = 64 * 1024


def build_play_url(video_token: str, ratio: str) -> str:
    query = urlencode({"video_id": video_token, "ratio": ratio})
    return f"{_PLAY_ENDPOINT}?{query}"


def _content_length(headers: httpx.Headers) -> int | None:
    value = headers.get("content-length")
    if value is None:
        content_range = headers.get("content-range")
        if content_range and "/" in content_range:
            value = content_range.rsplit("/", 1)[1]
    try:
        parsed = int(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


async def probe_play_url(
    video_token: str,
    ratio: str,
    *,
    referer: str,
    config: Any | None = None,
) -> DouyinQualityProbe | None:
    """Probe a play endpoint using ranged GET instead of HEAD."""

    play_url = build_play_url(video_token, ratio)
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "*/*",
        "Range": "bytes=0-1",
        "Referer": referer,
    }
    client_kwargs = build_httpx_client_kwargs(
        play_url,
        proxy_scope="douyin",
        timeout=_PROBE_TIMEOUT_SECONDS,
        follow_redirects=True,
        headers=headers,
        config=config,
    )
    try:
        async with httpx.AsyncClient(**client_kwargs) as client:
            response = await client.get(play_url)
            if response.status_code not in {200, 206}:
                logger.debug(
                    "[Douyin] 清晰度探测跳过: ratio=%s status=%s",
                    ratio,
                    response.status_code,
                )
                return None
            size_bytes = _content_length(response.headers)
            final_url = str(response.url)
            if not final_url:
                return None
            return DouyinQualityProbe(
                ratio=ratio,
                play_url=final_url,
                size_bytes=size_bytes,
            )
    except Exception as exc:
        logger.debug("[Douyin] 清晰度探测失败: ratio=%s err=%s", ratio, exc)
        return None


async def probe_qualities(
    info: DouyinVideoInfo,
    *,
    ratios: tuple[str, ...] = DEFAULT_RATIOS,
    config: Any | None = None,
) -> list[DouyinQualityProbe]:
    """Probe configured ratios and deduplicate identical files by size/url."""

    probes: list[DouyinQualityProbe] = []
    seen: set[tuple[int | None, str]] = set()
    for ratio in ratios:
        probe = await probe_play_url(
            info.play_token,
            ratio,
            referer=info.share_url,
            config=config,
        )
        if probe is None:
            continue
        key = (probe.size_bytes, probe.play_url if probe.size_bytes is None else "")
        if key in seen:
            continue
        seen.add(key)
        probes.append(probe)
    return probes


def build_download_filename(aweme_id: str, ratio: str) -> str:
    safe_id = "".join(ch if ch.isalnum() else "_" for ch in aweme_id).strip("_")
    safe_ratio = "".join(ch if ch.isalnum() else "_" for ch in ratio).strip("_")
    return f"douyin-{safe_id or 'video'}-{safe_ratio or 'video'}.mp4"


async def _download_probe(
    probe: DouyinQualityProbe,
    target_path: Path,
    *,
    referer: str,
    max_file_size_bytes: int,
    config: Any | None = None,
) -> int:
    part_path = target_path.with_suffix(f"{target_path.suffix}.part")
    timeout_seconds = max(get_request_timeout(480.0), 15.0)
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "*/*",
        "Referer": referer,
    }
    client_kwargs = build_httpx_client_kwargs(
        probe.play_url,
        proxy_scope="douyin",
        timeout=httpx.Timeout(timeout_seconds),
        follow_redirects=True,
        headers=headers,
        config=config,
    )
    downloaded = 0
    try:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        async with httpx.AsyncClient(**client_kwargs) as client:
            async with client.stream("GET", probe.play_url) as response:
                response.raise_for_status()
                response_size = _content_length(response.headers)
                if response_size is not None and response_size > max_file_size_bytes:
                    raise ValueError("抖音视频超过大小限制，已取消下载")
                async with aiofiles.open(part_path, "wb") as file:
                    async for chunk in response.aiter_bytes(
                        chunk_size=_DOWNLOAD_CHUNK_SIZE
                    ):
                        if not chunk:
                            continue
                        downloaded += len(chunk)
                        if downloaded > max_file_size_bytes:
                            raise ValueError(
                                "下载中发现抖音视频超过大小限制，已取消下载"
                            )
                        await file.write(chunk)
                    await file.flush()
        await asyncio.to_thread(part_path.replace, target_path)
        return downloaded
    finally:
        if part_path.exists():
            try:
                part_path.unlink()
            except OSError:
                pass


async def download_video(
    identifier: str,
    *,
    max_duration: int = 0,
    max_file_size: int = 0,
    prefer_ratios: tuple[str, ...] = DEFAULT_RATIOS,
    output_dir: Path | None = None,
    config: Any | None = None,
) -> tuple[Path | None, DouyinVideoInfo, str | None, int | None]:
    """Download a Douyin video.

    Returns:
        ``(path | None, info, selected_ratio | None, size_bytes | None)``.
        ``path`` is ``None`` when duration/size gates skip the download.
    """

    info = await get_video_info(identifier, config=config)
    if max_duration > 0 and info.duration > max_duration:
        logger.info(
            "[Douyin] 视频时长 %ds 超过限制 %ds，跳过下载: %s",
            info.duration,
            max_duration,
            info.aweme_id,
        )
        return None, info, None, None

    ratios = (
        tuple(ratio for ratio in prefer_ratios if str(ratio).strip()) or DEFAULT_RATIOS
    )
    probes = await probe_qualities(info, ratios=ratios, config=config)
    if not probes:
        raise RuntimeError("未探测到可用的抖音视频下载地址")

    max_size_bytes = max_file_size * 1024 * 1024 if max_file_size > 0 else 2**63 - 1
    selected: DouyinQualityProbe | None = None
    for probe in probes:
        if probe.size_bytes is None or probe.size_bytes <= max_size_bytes:
            selected = probe
            break
    if selected is None:
        largest = probes[0]
        return None, info, largest.ratio, largest.size_bytes

    if output_dir is None:
        output_dir = _DOUYIN_DOWNLOAD_DIR
    task_dir = ensure_dir(output_dir / uuid.uuid4().hex)
    file_path = task_dir / build_download_filename(info.aweme_id, selected.ratio)
    try:
        size_bytes = await _download_probe(
            selected,
            file_path,
            referer=info.share_url,
            max_file_size_bytes=max_size_bytes,
            config=config,
        )
        logger.info(
            "[Douyin] 下载完成: aweme_id=%s ratio=%s size=%sB",
            info.aweme_id,
            selected.ratio,
            size_bytes,
        )
        return file_path, info, selected.ratio, size_bytes
    except Exception:
        cleanup_path(task_dir)
        raise


def cleanup_path(path: Path) -> None:
    """Remove a file or task directory created by the downloader."""

    try:
        if path.is_file():
            parent = path.parent
            path.unlink()
            if parent.exists() and not any(parent.iterdir()):
                parent.rmdir()
            return
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)
    except Exception as exc:
        logger.warning("[Douyin] 清理下载路径失败 %s: %s", path, exc)


__all__ = [
    "DEFAULT_RATIOS",
    "DouyinDownloadResult",
    "build_download_filename",
    "build_play_url",
    "cleanup_path",
    "download_video",
    "probe_play_url",
    "probe_qualities",
]
