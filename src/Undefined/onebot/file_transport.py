"""OneBot 本地文件的单次准备、传输预算和引用替换。"""

import asyncio
import base64
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
import hashlib
import logging
from pathlib import Path, PurePosixPath, PureWindowsPath
import time
from typing import Any
from uuid import uuid4

from Undefined.config.onebot import FileSendSettings
from Undefined.onebot.file_errors import FileTransferError, OneBotAPIError
from Undefined.onebot.file_references import local_file_path, map_file_references
from Undefined.onebot.file_store import (
    DELIVERY_TIMEOUT,
    FILE_CHUNK_SIZE,
    OneBotFileStore,
)
from Undefined.utils import io

logger = logging.getLogger(__name__)
APICall = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]


@dataclass(frozen=True)
class PreparedFiles:
    replacements: dict[str, str]

    def apply(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        return map_file_references(
            action, params, lambda source: self.replacements.get(source, source)
        )


class OneBotFileTransport:
    def __init__(
        self,
        call_api: APICall,
        *,
        config_getter: Callable[[], Any] | None = None,
        store: OneBotFileStore | None = None,
        chunk_size: int = FILE_CHUNK_SIZE,
        timeout: float = DELIVERY_TIMEOUT,
    ) -> None:
        if chunk_size <= 0 or timeout <= 0:
            raise ValueError("文件传输分块大小和超时必须大于零")
        self.call_api = call_api
        self.config_getter = config_getter
        self.store = store if store is not None else OneBotFileStore()
        self.chunk_size = chunk_size
        self.timeout = timeout
        self._stream_lock = asyncio.Lock()

    @asynccontextmanager
    async def prepare(
        self, action: str, params: dict[str, Any]
    ) -> AsyncIterator[PreparedFiles]:
        sources: dict[str, Path] = {}

        def collect(source: str) -> str:
            path = local_file_path(source)
            if path is not None:
                sources[source] = path
            return source

        map_file_references(action, params, collect)
        if not sources:
            yield PreparedFiles({})
            return
        try:
            config = self.config_getter() if self.config_getter else None
            settings = (
                config
                if isinstance(config, FileSendSettings)
                else FileSendSettings.from_config(config)
            )
        except ValueError as exc:
            raise FileTransferError("config", str(exc), stage="config") from exc
        if settings.mode == "local":
            yield PreparedFiles({})
            return

        # 快照在排队前取得；排队不占传输预算，文本发送也不会取得此锁。
        async with AsyncExitStack() as stack:
            if settings.mode == "stream":
                await stack.enter_async_context(self._stream_lock)
            started = time.monotonic()
            stage = "prepare"
            outcome = "failed"
            try:
                async with asyncio.timeout(self.timeout):
                    prepared: dict[Path, str] = {}
                    replacements: dict[str, str] = {}
                    for source, path in sources.items():
                        resolved = await io.resolve_path(path)
                        if resolved not in prepared:
                            size = (await io.file_fingerprint(resolved))[2]
                            logger.info(
                                "[OneBot文件] mode=%s stage=prepare size=%d",
                                settings.mode,
                                size,
                            )
                            if settings.mode == "stream":
                                prepared[resolved] = await self._upload(resolved)
                            else:
                                prepared[resolved] = await self.store.publish(
                                    resolved, settings.host
                                )
                        replacements[source] = prepared[resolved]
                    logger.info(
                        "[OneBot文件] mode=%s stage=prepared elapsed=%.3fs",
                        settings.mode,
                        time.monotonic() - started,
                    )
                    stage = "send"
                    yield PreparedFiles(replacements)
                    outcome = "success"
            except TimeoutError as exc:
                raise FileTransferError(
                    settings.mode, "文件准备超过本次投递总时间预算", stage=stage
                ) from exc
            except OSError as exc:
                if stage != "prepare":
                    raise
                raise FileTransferError(
                    settings.mode, "无法读取或制作本地文件，请确认文件存在且可读"
                ) from exc
            except asyncio.CancelledError:
                outcome = "cancelled"
                raise
            finally:
                logger.info(
                    "[OneBot文件] mode=%s stage=%s elapsed=%.3fs status=%s",
                    settings.mode,
                    stage,
                    time.monotonic() - started,
                    outcome,
                )

    async def _upload(self, path: Path) -> str:
        before = await io.file_fingerprint(path)
        size = before[2]
        if not size:
            raise FileTransferError(
                "stream", "NapCat Stream API 不支持零字节文件，请使用 local 或 url 模式"
            )
        checksum = hashlib.sha256()
        async for chunk in io.iter_file_chunks(path, self.chunk_size):
            checksum.update(chunk)
        if await io.file_fingerprint(path) != before:
            raise FileTransferError("stream", "计算校验值期间源文件发生变化")
        expected_hash = checksum.hexdigest()
        total = (size + self.chunk_size - 1) // self.chunk_size
        stream_id = uuid4().hex
        common: dict[str, Any] = {
            "stream_id": stream_id,
            "total_chunks": total,
            "file_size": size,
            "expected_sha256": expected_hash,
            "filename": f"{uuid4().hex}{path.suffix}",
            "file_retention": int(self.timeout * 2 * 1000),
        }
        attempted = False
        complete = False
        unsupported = False
        try:
            sent_hash = hashlib.sha256()
            sent_size = 0
            index = 0
            async for chunk in io.iter_file_chunks(path, self.chunk_size):
                if index >= total:
                    raise FileTransferError("stream", "上传期间源文件发生变化")
                attempted = True
                result = await self.call_api(
                    "upload_file_stream",
                    {
                        **common,
                        "chunk_index": index,
                        "chunk_data": base64.b64encode(chunk).decode("ascii"),
                    },
                )
                self._ack(result, stream_id, "chunk_received", index + 1, total)
                sent_hash.update(chunk)
                sent_size += len(chunk)
                index += 1
                logger.debug(
                    "[OneBot文件] mode=stream stage=chunk received=%d total=%d",
                    index,
                    total,
                )
            if (
                sent_size != size
                or sent_hash.hexdigest() != expected_hash
                or await io.file_fingerprint(path) != before
            ):
                raise FileTransferError("stream", "上传期间源文件发生变化，已停止发送")
            result = await self.call_api(
                "upload_file_stream", {**common, "is_complete": True}
            )
            raw_data = result.get("data")
            complete = (
                isinstance(raw_data, dict)
                and raw_data.get("status") == "file_complete"
                and raw_data.get("stream_id") == stream_id
            )
            data = self._ack(result, stream_id, "file_complete", total, total)
            remote_path = data.get("file_path")
            if (
                not isinstance(remote_path, str)
                or not remote_path.strip()
                or "\x00" in remote_path
                or not (
                    PurePosixPath(remote_path).is_absolute()
                    or PureWindowsPath(remote_path).is_absolute()
                )
                or type(data.get("file_size")) is not int
                or data["file_size"] != size
                or not isinstance(data.get("sha256"), str)
                or data["sha256"].lower() != expected_hash
            ):
                raise FileTransferError(
                    "stream", "完成响应的文件路径、大小或 SHA-256 校验不符"
                )
            return remote_path
        except OneBotAPIError as exc:
            text = exc.message.casefold()
            unsupported = exc.retcode == 1404 or (
                "upload_file_stream" in text
                and any(
                    marker in text
                    for marker in (
                        "不支持",
                        "unsupported",
                        "not supported",
                        "unknown action",
                    )
                )
            )
            if unsupported:
                raise FileTransferError(
                    "stream",
                    '协议端不支持 upload_file_stream；请升级支持该扩展的 NapCat，或将 onebot.file_send_mode 改为 "local" 或 "url"',
                ) from exc
            raise FileTransferError(
                "stream", "协议端拒绝 Stream 上传，请检查 NapCat 日志及文件状态"
            ) from exc
        except (TimeoutError, ConnectionError, OSError) as exc:
            raise FileTransferError(
                "stream", "Stream 上传连接中断或等待确认超时"
            ) from exc
        except FileTransferError:
            raise
        except RuntimeError as exc:
            raise FileTransferError(
                "stream", "Stream 上传服务未连接或暂时不可用"
            ) from exc
        finally:
            if attempted and not complete and not unsupported:
                await self._reset(stream_id)

    @staticmethod
    def _ack(
        result: dict[str, Any], stream_id: str, status: str, count: int, total: int
    ) -> dict[str, Any]:
        data = result.get("data")
        expected_type = "response" if status == "file_complete" else "stream"
        if (
            result.get("status") != "ok"
            or result.get("retcode", 0) != 0
            or not isinstance(data, dict)
            or data.get("type") != expected_type
            or data.get("stream_id") != stream_id
            or data.get("status") != status
            or type(data.get("received_chunks")) is not int
            or data["received_chunks"] != count
            or type(data.get("total_chunks")) is not int
            or data["total_chunks"] != total
        ):
            raise FileTransferError("stream", "Stream 确认响应畸形或分块数量不符")
        return data

    async def _reset(self, stream_id: str) -> None:
        try:
            await asyncio.wait_for(
                self.call_api(
                    "upload_file_stream",
                    {
                        "stream_id": stream_id,
                        "reset": True,
                        "file_retention": int(self.timeout * 2 * 1000),
                    },
                ),
                timeout=5.0,
            )
        except OneBotAPIError as exc:
            if "stream reset completed" not in exc.message.lower():
                logger.warning("[OneBot文件] 重置未完成 Stream 失败")
        except (Exception, asyncio.CancelledError):
            logger.warning("[OneBot文件] 重置未完成 Stream 失败，保留原始错误")
