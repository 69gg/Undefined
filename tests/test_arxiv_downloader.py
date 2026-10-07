from __future__ import annotations

import asyncio
import os
import shutil
import threading
from io import BufferedWriter, FileIO
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, BinaryIO
from unittest.mock import AsyncMock

import httpx
import pytest

from Undefined.arxiv import downloader
from Undefined.arxiv.models import PaperInfo
from Undefined.utils import http_download


def _paper() -> PaperInfo:
    return PaperInfo(
        paper_id="2501.01234",
        title="isolated paper",
        authors=(),
        summary="",
        published="",
        updated="",
        primary_category="",
        abs_url="https://isolated.invalid/abs/2501.01234",
        pdf_url="https://isolated.invalid/pdf/2501.01234.pdf",
    )


@pytest.mark.asyncio
async def test_arxiv_preflight_cancel_removes_unowned_task_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ready = asyncio.Event()

    async def probe(*args: Any, **kwargs: Any) -> http_download.RemoteFileProbe:
        ready.set()
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    monkeypatch.setattr(downloader, "_ARXIV_DOWNLOAD_DIR", tmp_path)
    monkeypatch.setattr(downloader, "probe_remote_file", probe)
    task = asyncio.create_task(
        downloader.download_paper_pdf(_paper(), max_file_size_mb=1)
    )
    await ready.wait()
    assert len(list(tmp_path.iterdir())) == 1
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 1)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_arxiv_stream_cancel_does_not_wait_for_network_completion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ready = asyncio.Event()

    class BlockedStream(httpx.AsyncByteStream):
        async def __aiter__(self) -> AsyncIterator[bytes]:
            yield b"x" * http_download.DEFAULT_DOWNLOAD_CHUNK_SIZE
            ready.set()
            await asyncio.Event().wait()

    client_type = httpx.AsyncClient

    def reply(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=BlockedStream(), request=request)

    def client(**kwargs: Any) -> httpx.AsyncClient:
        return client_type(transport=httpx.MockTransport(reply), **kwargs)

    paper = _paper()
    monkeypatch.setattr(downloader, "_ARXIV_DOWNLOAD_DIR", tmp_path)
    monkeypatch.setattr(
        downloader,
        "probe_remote_file",
        AsyncMock(
            return_value=http_download.RemoteFileProbe(
                paper.pdf_url, httpx.Headers(), None
            )
        ),
    )
    monkeypatch.setattr(httpx, "AsyncClient", client)
    task = asyncio.create_task(downloader.download_paper_pdf(paper, max_file_size_mb=1))
    await ready.wait()
    assert len(list(tmp_path.rglob("*.part"))) == 1
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 1)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("replaced_before_cancel", [False, True])
async def test_arxiv_cancel_waits_for_actual_replace_before_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    replaced_before_cancel: bool,
) -> None:
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    original_replace = os.replace

    def replace(source: Path, target: Path) -> None:
        if replaced_before_cancel:
            original_replace(source, target)
        started.set()
        if not release.wait(5):
            raise AssertionError("replace thread was not released")
        if not replaced_before_cancel:
            original_replace(source, target)
        finished.set()

    client_type = httpx.AsyncClient

    def reply(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"complete PDF bytes", request=request)

    def client(**kwargs: Any) -> httpx.AsyncClient:
        return client_type(transport=httpx.MockTransport(reply), **kwargs)

    paper = _paper()
    monkeypatch.setattr(downloader, "_ARXIV_DOWNLOAD_DIR", tmp_path)
    monkeypatch.setattr(
        downloader,
        "probe_remote_file",
        AsyncMock(
            return_value=http_download.RemoteFileProbe(
                paper.pdf_url, httpx.Headers(), None
            )
        ),
    )
    monkeypatch.setattr(httpx, "AsyncClient", client)
    monkeypatch.setattr(os, "replace", replace)
    task = asyncio.create_task(downloader.download_paper_pdf(paper, max_file_size_mb=1))
    try:
        assert await asyncio.to_thread(started.wait, 2)
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        assert not finished.is_set()
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 2)
    assert finished.is_set()
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["open", "close"])
async def test_arxiv_cancel_waits_for_open_and_closes_acquired_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, phase: str
) -> None:
    import aiofiles.threadpool

    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    handles: list[BinaryIO] = []
    original_open = open

    class BlockingWriter(BufferedWriter):
        def close(self) -> None:
            if not self.closed:
                started.set()
                if not release.wait(5):
                    raise AssertionError("close thread was not released")
                super().close()
                finished.set()

    def open_file(file: str | Path, *args: Any, **kwargs: Any) -> Any:
        handle = (
            BlockingWriter(FileIO(file, mode="wb"))
            if phase == "close"
            else original_open(file, *args, **kwargs)
        )
        handles.append(handle)
        if phase == "open":
            started.set()
            if not release.wait(5):
                raise AssertionError("open thread was not released")
            finished.set()
        return handle

    client_type = httpx.AsyncClient

    def reply(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"PDF bytes", request=request)

    def client(**kwargs: Any) -> httpx.AsyncClient:
        return client_type(transport=httpx.MockTransport(reply), **kwargs)

    paper = _paper()
    monkeypatch.setattr(downloader, "_ARXIV_DOWNLOAD_DIR", tmp_path)
    monkeypatch.setattr(
        downloader,
        "probe_remote_file",
        AsyncMock(
            return_value=http_download.RemoteFileProbe(
                paper.pdf_url, httpx.Headers(), None
            )
        ),
    )
    monkeypatch.setattr(httpx, "AsyncClient", client)
    monkeypatch.setattr(aiofiles.threadpool, "sync_open", open_file)
    task = asyncio.create_task(downloader.download_paper_pdf(paper, max_file_size_mb=1))
    try:
        assert await asyncio.to_thread(started.wait, 2)
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(asyncio.shield(task), 0.03)
        assert not finished.is_set()
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 2)
    assert finished.is_set()
    assert handles[0].closed
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_arxiv_cleanup_waits_through_repeated_cancellation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    task_dir = tmp_path / "download-task"
    task_dir.mkdir()
    (task_dir / "paper.pdf").write_bytes(b"PDF")
    started = threading.Event()
    release = threading.Event()

    def remove(path: Path) -> None:
        started.set()
        if not release.wait(5):
            raise AssertionError("cleanup thread was not released")
        shutil.rmtree(path)

    async def cleanup(path: Path) -> None:
        await asyncio.to_thread(remove, path)

    monkeypatch.setattr(downloader, "cleanup_download_dir", cleanup)
    task = asyncio.create_task(downloader.cleanup_download_path(task_dir))
    try:
        assert await asyncio.to_thread(started.wait, 2)
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(asyncio.shield(task), 0.03)
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 2)
    assert not task_dir.exists()
