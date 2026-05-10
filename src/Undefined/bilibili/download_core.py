"""B 站 DASH 流下载与 ffmpeg 合并。"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Protocol

from Undefined.bilibili.errors import DownloadError, FFmpegError, FFmpegNotFoundError
from Undefined.bilibili.models import DownloadResult, VideoInfo

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

_INVALID_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|]')
_CHUNK_SIZE = 64 * 1024


class BilibiliDownloadClient(Protocol):
    @property
    def http_client(self) -> Any: ...

    def get_video_info(self, bvid: str) -> VideoInfo: ...

    def get_playurl(self, bvid: str, cid: int) -> dict[str, Any]: ...


def _select_quality(available_qualities: list[int], prefer: int) -> int:
    if not available_qualities:
        return prefer
    if prefer in available_qualities:
        return prefer
    lower = [quality for quality in available_qualities if quality <= prefer]
    if lower:
        return max(lower)
    return min(available_qualities)


def _sanitize_filename(text: str) -> str:
    cleaned = _INVALID_FILENAME_CHARS.sub("_", text).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned or "bilibili_video"


def _next_available_path(path: Path) -> Path:
    index = 1
    while True:
        candidate = path.with_name(f"{path.stem} ({index}){path.suffix}")
        if not candidate.exists():
            return candidate
        index += 1


def _prepare_output_path(
    save_path: str | Path,
    *,
    title: str,
    bvid: str,
    overwrite: bool,
) -> Path:
    target = Path(save_path).expanduser()
    filename = f"{_sanitize_filename(title)}-{bvid}.mp4"

    if target.exists() and target.is_dir():
        output = target / filename
    elif target.suffix:
        output = target.with_suffix(".mp4")
    else:
        output = target / filename

    output.parent.mkdir(parents=True, exist_ok=True)

    if output.exists():
        if overwrite:
            output.unlink()
        else:
            output = _next_available_path(output)

    return output


def _pick_stream_url(stream: dict[str, Any] | None) -> str:
    if stream is None:
        return ""
    return str(stream.get("baseUrl") or stream.get("base_url") or "")


def _download_stream(client: BilibiliDownloadClient, url: str, dest: Path) -> None:
    if not url:
        raise DownloadError("视频流 URL 为空")

    with client.http_client.stream("GET", url) as response:
        response.raise_for_status()
        with dest.open("wb") as file:
            for chunk in response.iter_bytes(chunk_size=_CHUNK_SIZE):
                file.write(chunk)


def _merge_av(video_path: Path, audio_path: Path, output_path: Path) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise FFmpegNotFoundError("找不到 ffmpeg，请安装 ffmpeg 后再下载视频")

    cmd = [
        ffmpeg,
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
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()
        raise FFmpegError(f"ffmpeg 合并失败: {stderr[-500:]}")


def download_video(
    api_client: BilibiliDownloadClient,
    *,
    bvid: str,
    save_path: str | Path,
    prefer_quality: int = 80,
    overwrite: bool = True,
) -> DownloadResult:
    """下载 B 站视频到指定目录或文件路径。"""
    info = api_client.get_video_info(bvid)
    data = api_client.get_playurl(bvid, info.cid)

    dash = data.get("dash")
    if not isinstance(dash, dict):
        raise DownloadError("该视频未提供可下载的 DASH 流")

    video_streams_raw = dash.get("video")
    if not isinstance(video_streams_raw, list) or not video_streams_raw:
        raise DownloadError("未找到可用视频流")

    video_streams = [stream for stream in video_streams_raw if isinstance(stream, dict)]
    audio_streams_raw = dash.get("audio")
    audio_streams: list[dict[str, Any]] = []
    if isinstance(audio_streams_raw, list):
        audio_streams = [
            stream for stream in audio_streams_raw if isinstance(stream, dict)
        ]

    available_qns = sorted(
        {
            int(stream.get("id", 0))
            for stream in video_streams
            if stream.get("id") is not None
        },
        reverse=True,
    )
    actual_qn = _select_quality(available_qns, prefer_quality)

    target_videos = [
        stream for stream in video_streams if int(stream.get("id", 0)) == actual_qn
    ]
    if not target_videos:
        target_videos = video_streams
        actual_qn = int(target_videos[0].get("id", prefer_quality))

    video_stream = max(
        target_videos, key=lambda stream: int(stream.get("bandwidth", 0))
    )
    audio_stream = None
    if audio_streams:
        audio_stream = max(
            audio_streams,
            key=lambda stream: int(stream.get("bandwidth", 0)),
        )

    output_path = _prepare_output_path(
        save_path,
        title=info.title,
        bvid=info.bvid,
        overwrite=overwrite,
    )
    work_dir = Path(
        tempfile.mkdtemp(prefix=f"bilibili-{bvid}-", dir=output_path.parent)
    )
    video_tmp = work_dir / "video.m4s"
    audio_tmp = work_dir / "audio.m4s"

    try:
        _download_stream(api_client, _pick_stream_url(video_stream), video_tmp)
        audio_url = _pick_stream_url(audio_stream)
        if audio_stream is not None and audio_url:
            _download_stream(api_client, audio_url, audio_tmp)
            _merge_av(video_tmp, audio_tmp, output_path)
        else:
            video_tmp.replace(output_path)
    except DownloadError:
        raise
    except Exception as exc:
        raise DownloadError(str(exc)) from exc
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)

    actual_quality = QUALITY_MAP.get(actual_qn, str(actual_qn))
    return DownloadResult(
        path=output_path,
        size_bytes=output_path.stat().st_size,
        quality=actual_qn,
        quality_label=actual_quality,
        video_info=info,
    )
