from __future__ import annotations

import asyncio
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

import aiofiles
import httpx

from Undefined.skills.http_client import request_with_retry

DEFAULT_DOWNLOAD_CHUNK_SIZE = 64 * 1024


@dataclass(frozen=True)
class RemoteFileProbe:
    final_url: str
    headers: httpx.Headers
    content_length: int | None


def parse_content_length(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    if parsed <= 0:
        return None
    return parsed


async def probe_remote_file(
    url: str,
    *,
    timeout_seconds: float,
    follow_redirects: bool = True,
    context: dict[str, object] | None = None,
) -> RemoteFileProbe:
    response = await request_with_retry(
        "HEAD",
        url,
        timeout=timeout_seconds,
        follow_redirects=follow_redirects,
        context=context,
    )
    return RemoteFileProbe(
        final_url=str(response.url),
        headers=response.headers,
        content_length=parse_content_length(response.headers.get("content-length")),
    )


async def download_remote_file(
    url: str,
    target_path: Path,
    *,
    max_file_size_bytes: int,
    timeout_seconds: float,
    expected_size: int | None = None,
    follow_redirects: bool = True,
    chunk_size: int = DEFAULT_DOWNLOAD_CHUNK_SIZE,
) -> tuple[str, int]:
    part_path = target_path.with_suffix(f"{target_path.suffix}.part")

    try:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        downloaded_size = 0

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_seconds),
            follow_redirects=follow_redirects,
        ) as client:
            async with client.stream("GET", url) as response:
                response.raise_for_status()

                response_size = parse_content_length(
                    response.headers.get("content-length")
                )
                if response_size is not None and response_size > max_file_size_bytes:
                    raise ValueError("远程文件超过大小限制，已取消下载")
                if (
                    expected_size is not None
                    and response_size is not None
                    and response_size != expected_size
                ):
                    raise ValueError("远程文件大小与预检不一致，已取消下载")

                async with aiofiles.open(part_path, "wb") as f:
                    async for chunk in response.aiter_bytes(chunk_size=chunk_size):
                        if not chunk:
                            continue
                        downloaded_size += len(chunk)
                        if downloaded_size > max_file_size_bytes:
                            raise ValueError("下载中发现文件超过大小限制，已取消下载")
                        if (
                            expected_size is not None
                            and downloaded_size > expected_size
                        ):
                            raise ValueError("下载中发现文件超出预检大小，已取消下载")
                        await f.write(chunk)
                    await f.flush()

        if expected_size is not None and downloaded_size != expected_size:
            raise ValueError("下载完成后大小与预检不一致，已取消下载")

        await asyncio.to_thread(os.replace, part_path, target_path)
        return str(target_path.resolve()), downloaded_size
    finally:
        if part_path.exists():
            try:
                part_path.unlink()
            except OSError:
                pass


async def cleanup_download_dir(path: Path) -> None:
    def _cleanup() -> None:
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)

    await asyncio.to_thread(_cleanup)
