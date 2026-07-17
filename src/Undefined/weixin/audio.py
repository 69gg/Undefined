"""微信出站语音的音频归一化与 Tencent SILK 编码。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Final

import pysilk
from weixin_ilink_client.constants import TENCENT_SILK_HEADER

from Undefined.utils import io

VOICE_SAMPLE_RATE: Final[int] = 24_000
VOICE_BITS_PER_SAMPLE: Final[int] = 16
VOICE_CHANNELS: Final[int] = 1
VOICE_BIT_RATE: Final[int] = 24_000
VOICE_SOURCE_SUFFIXES: Final[frozenset[str]] = frozenset(
    {
        ".aac",
        ".flac",
        ".m4a",
        ".mp3",
        ".ogg",
        ".opus",
        ".silk",
        ".wav",
        ".webm",
        ".wma",
    }
)
_PCM_BYTES_PER_SAMPLE: Final[int] = VOICE_BITS_PER_SAMPLE // 8
_READ_CHUNK_BYTES: Final[int] = 64 * 1024


class WeixinVoiceConversionError(ValueError):
    """音频无法安全转换为微信 Tencent SILK。"""


@dataclass(frozen=True, slots=True)
class PreparedWeixinVoice:
    """完成发送前校验和编码的微信语音。"""

    content: bytes
    duration_ms: int
    sample_rate: int = VOICE_SAMPLE_RATE
    bits_per_sample: int = VOICE_BITS_PER_SAMPLE


async def prepare_weixin_voice(
    file_path: str | Path,
    *,
    maximum_bytes: int,
) -> PreparedWeixinVoice:
    """将本地音频完整预处理为可发送的 Tencent SILK。"""

    if maximum_bytes <= 0:
        raise WeixinVoiceConversionError("微信语音大小限制无效")
    path = await io.resolve_path(file_path)
    if not await io.is_file(path):
        raise WeixinVoiceConversionError("微信语音文件不存在")
    source_size = await io.get_file_size(path)
    if source_size <= 0:
        raise WeixinVoiceConversionError("微信语音文件为空")
    if source_size > maximum_bytes:
        raise WeixinVoiceConversionError(
            f"微信语音超过大小限制: {source_size} > {maximum_bytes} bytes"
        )

    if path.suffix.lower() == ".silk":
        content = await io.read_bytes(path)
        if not _is_tencent_silk(content):
            raise WeixinVoiceConversionError("语音文件不是有效的 Tencent SILK")
        pcm = await _decode_silk(content)
    else:
        pcm = await _normalize_audio_to_pcm(path, maximum_bytes=maximum_bytes)
        content = await _encode_tencent_silk(pcm)

    if len(content) > maximum_bytes:
        raise WeixinVoiceConversionError(
            f"编码后的微信语音超过大小限制: {len(content)} > {maximum_bytes} bytes"
        )
    duration_ms = _pcm_duration_ms(pcm)
    return PreparedWeixinVoice(content=content, duration_ms=duration_ms)


def _is_tencent_silk(content: bytes) -> bool:
    return len(content) > len(TENCENT_SILK_HEADER) and content.startswith(
        TENCENT_SILK_HEADER
    )


def _pcm_duration_ms(pcm: bytes) -> int:
    frame_bytes = VOICE_CHANNELS * _PCM_BYTES_PER_SAMPLE
    if not pcm or len(pcm) % frame_bytes != 0:
        raise WeixinVoiceConversionError("音频转换结果不是有效的 16-bit PCM")
    denominator = VOICE_SAMPLE_RATE * frame_bytes
    return max(1, round(len(pcm) * 1000 / denominator))


async def _normalize_audio_to_pcm(path: Path, *, maximum_bytes: int) -> bytes:
    ffmpeg = await io.find_executable("ffmpeg")
    if ffmpeg is None:
        raise WeixinVoiceConversionError("发送微信语音需要安装 FFmpeg")
    try:
        process = await asyncio.create_subprocess_exec(
            ffmpeg,
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(path),
            "-vn",
            "-acodec",
            "pcm_s16le",
            "-f",
            "s16le",
            "-ac",
            str(VOICE_CHANNELS),
            "-ar",
            str(VOICE_SAMPLE_RATE),
            "pipe:1",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except OSError as exc:
        raise WeixinVoiceConversionError("无法启动 FFmpeg 音频转换") from exc

    stdout = process.stdout
    stderr = process.stderr
    if stdout is None or stderr is None:
        process.kill()
        await process.wait()
        raise WeixinVoiceConversionError("FFmpeg 音频管道初始化失败")

    stderr_task = asyncio.create_task(stderr.read())
    chunks: list[bytes] = []
    size = 0
    try:
        while chunk := await stdout.read(_READ_CHUNK_BYTES):
            size += len(chunk)
            if size > maximum_bytes:
                raise WeixinVoiceConversionError("转换后的 PCM 音频超过大小限制")
            chunks.append(chunk)
        return_code = await process.wait()
        error_output = await stderr_task
    except BaseException:
        if process.returncode is None:
            process.kill()
            await process.wait()
        if not stderr_task.done():
            stderr_task.cancel()
        await asyncio.gather(stderr_task, return_exceptions=True)
        raise

    if return_code != 0:
        detail = error_output.decode("utf-8", errors="replace").strip()[-500:]
        raise WeixinVoiceConversionError(
            f"FFmpeg 无法转换该音频: {detail or '未知错误'}"
        )
    pcm = b"".join(chunks)
    if not pcm:
        raise WeixinVoiceConversionError("FFmpeg 未生成有效音频")
    return pcm


async def _encode_tencent_silk(pcm: bytes) -> bytes:
    def encode() -> bytes:
        source = BytesIO(pcm)
        target = BytesIO()
        pysilk.encode(
            source,
            target,
            VOICE_SAMPLE_RATE,
            VOICE_BIT_RATE,
            tencent=True,
        )
        return target.getvalue()

    try:
        content = await asyncio.to_thread(encode)
    except Exception as exc:
        raise WeixinVoiceConversionError("Tencent SILK 编码失败") from exc
    if not _is_tencent_silk(content):
        raise WeixinVoiceConversionError("Tencent SILK 编码结果无效")
    return content


async def _decode_silk(content: bytes) -> bytes:
    def decode() -> bytes:
        source = BytesIO(content)
        target = BytesIO()
        pysilk.decode(source, target, VOICE_SAMPLE_RATE)
        return target.getvalue()

    try:
        pcm = await asyncio.to_thread(decode)
    except Exception as exc:
        raise WeixinVoiceConversionError("Tencent SILK 解码校验失败") from exc
    if not pcm:
        raise WeixinVoiceConversionError("Tencent SILK 不包含有效音频")
    return pcm
