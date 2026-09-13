"""Runtime 专用的单文件临时授权及副本生命周期。"""

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
import logging
import mimetypes
from pathlib import Path
import re
import secrets
import time
from collections.abc import AsyncIterator, Callable
from uuid import uuid4

from Undefined.config.models import format_netloc
from Undefined.onebot.file_errors import FileTransferError
from Undefined.utils import io
from Undefined.utils.paths import ONEBOT_FILE_CACHE_DIR

logger = logging.getLogger(__name__)
DELIVERY_TIMEOUT = 480.0
FILE_RETENTION = DELIVERY_TIMEOUT * 2
FILE_CHUNK_SIZE = 64 * 1024
FILE_ROUTE = "/api/v1/onebot/files/{file_id}"
FILE_ROUTE_NAME = "onebot-file-download"
_CACHE_NAME = re.compile(r"^onebot-(\d+)-[0-9a-f]{32}$")


@dataclass
class PublishedFile:
    path: Path
    token: str
    name: str
    content_type: str
    expires_at: float
    readers: int = 0


class FileAuthorizationError(Exception):
    def __init__(self, status: int) -> None:
        self.status = status


class OneBotFileStore:
    def __init__(
        self,
        cache_dir: Path = ONEBOT_FILE_CACHE_DIR,
        *,
        retention: float = FILE_RETENTION,
        chunk_size: int = FILE_CHUNK_SIZE,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if retention <= 0 or chunk_size <= 0:
            raise ValueError("URL 文件保留期和复制分块大小必须大于零")
        self.cache_dir = cache_dir
        self.retention = retention
        self.chunk_size = chunk_size
        self.clock = clock
        self.port: int | None = None
        self._files: dict[str, PublishedFile] = {}
        self._cleanup_task: asyncio.Task[None] | None = None

    async def start(self, port: int) -> None:
        await io.ensure_dir(self.cache_dir)
        # 只回收本模块命名且已过期的遗留副本，不能清空整个缓存根目录。
        for path, is_dir in await io.list_directory_entries(self.cache_dir):
            match = _CACHE_NAME.fullmatch(path.name)
            if is_dir and match and int(match[1]) <= self.clock() * 1000:
                await io.delete_tree(path)
        self.port = port
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    def unavailable(self) -> None:
        self.port = None

    async def stop(self) -> None:
        self.unavailable()
        if self._cleanup_task is not None:
            self._cleanup_task.cancel()
            await asyncio.gather(self._cleanup_task, return_exceptions=True)
            self._cleanup_task = None
        await self.cleanup(all_files=True)

    async def publish(self, source: Path, host: str) -> str:
        port = self.port
        if port is None:
            raise FileTransferError(
                "url", "Runtime 文件服务未就绪，请启动 Runtime 并确认监听设置"
            )
        file_id = uuid4().hex
        pending_expiry = self.clock() + self.retention + DELIVERY_TIMEOUT
        directory = self.cache_dir / f"onebot-{int(pending_expiry * 1000)}-{file_id}"
        try:
            before = await io.file_fingerprint(source)
            await io.copy_file_atomic(source, directory / "content", self.chunk_size)
            if await io.file_fingerprint(source) != before:
                raise FileTransferError(
                    "url", "制作下载副本期间源文件发生变化，请重新生成后发送"
                )
            if self.port is None:
                raise FileTransferError("url", "Runtime 文件服务已经停止")
            expiry = self.clock() + self.retention
            final = self.cache_dir / f"onebot-{int(expiry * 1000)}-{file_id}"
            await io.move_path(directory, final)
            directory = final
            if self.port != port:
                raise FileTransferError("url", "Runtime 文件服务已经停止或重新绑定")
            token = secrets.token_urlsafe(32)
            self._files[file_id] = PublishedFile(
                path=final / "content",
                token=token,
                name=source.name,
                content_type=mimetypes.guess_type(source.name)[0]
                or "application/octet-stream",
                expires_at=expiry,
            )
            return f"http://{format_netloc(host, port)}{FILE_ROUTE.format(file_id=file_id)}?token={token}"
        except BaseException:
            await io.delete_tree(directory)
            raise

    @asynccontextmanager
    async def acquire(self, file_id: str, token: str) -> AsyncIterator[PublishedFile]:
        if not token:
            raise FileAuthorizationError(401)
        entry = self._files.get(file_id)
        if entry is None or entry.expires_at <= self.clock():
            raise FileAuthorizationError(404)
        if not token.isascii() or not secrets.compare_digest(entry.token, token):
            raise FileAuthorizationError(401)
        entry.readers += 1
        try:
            if not await io.is_file(entry.path):
                raise FileAuthorizationError(404)
            yield entry
        finally:
            entry.readers -= 1
            if entry.expires_at <= self.clock() or self.port is None:
                await self.cleanup(all_files=self.port is None)

    async def cleanup(self, *, all_files: bool = False) -> None:
        for file_id, entry in list(self._files.items()):
            if not entry.readers and (all_files or entry.expires_at <= self.clock()):
                # 删除前撤销登记，确保新请求不能在删除期间取得租约。
                self._files.pop(file_id, None)
                await io.delete_tree(entry.path.parent)

    async def _cleanup_loop(self) -> None:
        while True:
            await asyncio.sleep(min(60.0, self.retention))
            try:
                await self.cleanup()
            except OSError:
                logger.warning("[OneBot文件] 清理过期 URL 副本失败", exc_info=True)
