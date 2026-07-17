from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from Undefined.utils import io as async_io
from Undefined.weixin import audio
from Undefined.weixin.audio import WeixinVoiceConversionError


@pytest.mark.asyncio
async def test_prepare_weixin_voice_encodes_normalized_pcm(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "voice.wav"
    await async_io.write_bytes(source, b"RIFF-test")
    pcm = b"\x00\x00" * (audio.VOICE_SAMPLE_RATE // 5)
    normalize = AsyncMock(return_value=pcm)
    monkeypatch.setattr(audio, "_normalize_audio_to_pcm", normalize)

    prepared = await audio.prepare_weixin_voice(source, maximum_bytes=1024 * 1024)

    assert prepared.content.startswith(b"\x02#!SILK_V3")
    assert prepared.duration_ms == 200
    assert prepared.sample_rate == 24_000
    assert prepared.bits_per_sample == 16
    normalize.assert_awaited_once_with(source.resolve(), maximum_bytes=1024 * 1024)


@pytest.mark.asyncio
async def test_prepare_weixin_voice_reuses_valid_tencent_silk(
    tmp_path: Path,
) -> None:
    pcm = b"\x00\x00" * (audio.VOICE_SAMPLE_RATE // 10)
    content = await audio._encode_tencent_silk(pcm)
    source = tmp_path / "voice.silk"
    await async_io.write_bytes(source, content)

    prepared = await audio.prepare_weixin_voice(source, maximum_bytes=1024 * 1024)

    assert prepared.content == content
    assert prepared.duration_ms == 100


@pytest.mark.asyncio
async def test_prepare_weixin_voice_reports_missing_ffmpeg(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "voice.wav"
    await async_io.write_bytes(source, b"RIFF-test")
    monkeypatch.setattr(async_io, "find_executable", AsyncMock(return_value=None))

    with pytest.raises(WeixinVoiceConversionError, match="FFmpeg"):
        await audio.prepare_weixin_voice(source, maximum_bytes=1024 * 1024)


@pytest.mark.asyncio
async def test_prepare_weixin_voice_rejects_oversized_source(
    tmp_path: Path,
) -> None:
    source = tmp_path / "voice.wav"
    await async_io.write_bytes(source, b"12345")

    with pytest.raises(WeixinVoiceConversionError, match="超过大小限制"):
        await audio.prepare_weixin_voice(source, maximum_bytes=4)


@pytest.mark.asyncio
async def test_normalize_audio_timeout_cleans_up_ffmpeg(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class BlockingReader:
        def __init__(self) -> None:
            self.cancelled = False

        async def read(self, _size: int = -1) -> bytes:
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                self.cancelled = True
                raise
            return b""

    class FakeProcess:
        def __init__(self) -> None:
            self.stdout = BlockingReader()
            self.stderr = BlockingReader()
            self.returncode: int | None = None
            self.killed = False
            self.wait_calls = 0

        def kill(self) -> None:
            self.killed = True

        async def wait(self) -> int:
            self.wait_calls += 1
            if self.killed:
                self.returncode = -9
                return self.returncode
            await asyncio.Event().wait()
            return 0

    process = FakeProcess()

    async def fake_create_subprocess_exec(
        *_args: object,
        **_kwargs: object,
    ) -> FakeProcess:
        return process

    monkeypatch.setattr(
        async_io,
        "find_executable",
        AsyncMock(return_value="/usr/bin/ffmpeg"),
    )
    monkeypatch.setattr(
        asyncio,
        "create_subprocess_exec",
        fake_create_subprocess_exec,
    )
    monkeypatch.setattr(audio, "_FFMPEG_CONVERSION_TIMEOUT_SECONDS", 0.01)

    with pytest.raises(TimeoutError):
        await audio._normalize_audio_to_pcm(
            tmp_path / "voice.wav",
            maximum_bytes=1024,
        )

    assert process.killed is True
    assert process.wait_calls == 1
    assert process.stderr.cancelled is True
