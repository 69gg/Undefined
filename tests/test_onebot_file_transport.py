from __future__ import annotations

import asyncio
import base64
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from copy import deepcopy
import hashlib
import json
import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from websockets.asyncio.server import ServerConnection, serve

from Undefined.config.onebot import FileSendSettings
from Undefined.context import RequestContext
from Undefined.onebot.client import OneBotClient, OneBotDeliveryUncertainError
from Undefined.onebot.file_errors import FileTransferError, OneBotAPIError
from Undefined.onebot.file_references import map_file_references
from Undefined.onebot.file_transport import OneBotFileTransport
from Undefined.utils.coerce import was_message_sent
from Undefined.utils.logging import sanitize_data
from Undefined.attachments import AttachmentRegistry
from Undefined.utils.sender import MessageSender


class NapCat:
    """模拟实际 WebSocket 协议，严格检查逐块请求、完成请求及文件字节。"""

    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []
        self.echoes: list[str] = []
        self.chunks: dict[str, list[bytes]] = {}
        self.completed: dict[str, bytes] = {}
        self.remote_path = r"C:\NapCat\temp\uploaded.bin"
        self.failure = ""
        self.block = asyncio.Event()
        self.received = asyncio.Event()

    async def respond(
        self,
        action: str,
        params: dict[str, Any] | None = None,
        *,
        suppress_error_retcodes: set[int] | None = None,
    ) -> dict[str, Any]:
        params = params or {}
        self.requests.append({"action": action, "params": deepcopy(params)})
        if action != "upload_file_stream":
            if self.failure == "send_blocked":
                self.received.set()
                await self.block.wait()
            if self.failure == "delivery_timeout":
                raise OneBotDeliveryUncertainError(action, "Timeout")
            if self.failure == "fallback" and action.startswith("upload_"):
                raise OneBotAPIError("file action failed", 1200)
            return {"status": "ok", "data": {"message_id": 42}}
        stream_id = params["stream_id"]
        if params.get("reset"):
            self.chunks.pop(stream_id, None)
            if self.failure == "reset_failure":
                raise OSError("reset failed")
            raise OneBotAPIError("Stream reset completed", 1200)
        if self.failure == "unsupported":
            raise OneBotAPIError("不支持的API upload_file_stream", 1404)
        if self.failure == "network":
            raise ConnectionError("lost connection")
        if self.failure == "blocked":
            self.received.set()
            await self.block.wait()
        total = params["total_chunks"]
        assert params["file_retention"] > 0
        if "chunk_data" in params:
            assert "is_complete" not in params
            chunks = self.chunks.setdefault(stream_id, [])
            assert params["chunk_index"] == len(chunks)
            chunks.append(base64.b64decode(params["chunk_data"], validate=True))
            data = {
                "type": "stream",
                "stream_id": stream_id,
                "status": "chunk_received",
                "received_chunks": len(chunks),
                "total_chunks": total,
            }
            if self.failure in {"ack", "reset_failure"}:
                data["received_chunks"] = 0
        else:
            assert params["is_complete"] is True
            blob = b"".join(self.chunks[stream_id])
            assert len(self.chunks[stream_id]) == total
            assert len(blob) == params["file_size"]
            assert hashlib.sha256(blob).hexdigest() == params["expected_sha256"]
            self.completed[stream_id] = blob
            data = {
                "type": "response",
                "stream_id": stream_id,
                "status": "file_complete",
                "received_chunks": total,
                "total_chunks": total,
                "file_path": self.remote_path,
                "file_size": len(blob),
                "sha256": hashlib.sha256(blob).hexdigest(),
            }
            if self.failure == "hash":
                data["sha256"] = "0" * 64
        return {"status": "ok", "retcode": 0, "data": data}

    async def websocket(self, ws: ServerConnection) -> None:
        async for payload in ws:
            request = json.loads(payload)
            self.echoes.append(request["echo"])
            is_upload = request["action"] == "upload_file_stream"
            if (self.failure == "disconnect_upload" and is_upload) or (
                self.failure == "disconnect_send" and not is_upload
            ):
                await ws.close()
                return
            try:
                response = await self.respond(request["action"], request["params"])
            except OneBotAPIError as exc:
                response = {
                    "status": "failed",
                    "retcode": exc.retcode,
                    "message": exc.message,
                }
            await ws.send(
                json.dumps(
                    {**response, "echo": request["echo"], "stream": "stream-action"}
                )
            )


@asynccontextmanager
async def connected(napcat: NapCat, token: str = "") -> AsyncIterator[OneBotClient]:
    server_logger = logging.getLogger("tests.napcat")
    server_logger.setLevel(logging.INFO)
    async with serve(napcat.websocket, "127.0.0.1", 0, logger=server_logger) as server:
        port = server.sockets[0].getsockname()[1]
        client = OneBotClient(f"ws://127.0.0.1:{port}", token)
        await client.connect()
        task = asyncio.create_task(client.run())
        try:
            yield client
        finally:
            napcat.block.set()
            await client.disconnect()
            await task


@pytest.mark.parametrize("size", [1, 65535, 65536, 65537, 131072])
async def test_real_websocket_stream_bytes_and_sequence(
    tmp_path: Path, size: int, caplog: pytest.LogCaptureFixture
) -> None:
    path = tmp_path / "中文 音频.bin"
    blob = bytes(range(256)) * (size // 256) + bytes(range(size % 256))
    path.write_bytes(blob)
    napcat = NapCat()
    caplog.set_level("DEBUG")
    async with connected(napcat) as client:
        original = [
            {"type": "video", "data": {"file": path.as_uri(), "thumb": str(path)}}
        ]
        before = deepcopy(original)
        await client.send_group_message(1, original)
        assert original == before
    assert list(napcat.completed.values()) == [blob]
    assert len(set(napcat.echoes)) == len(napcat.requests)
    uploads = [r["params"] for r in napcat.requests[:-1]]
    assert len(uploads) == (size + 65535) // 65536 + 1
    assert uploads[-1]["is_complete"] is True
    assert uploads[0]["file_retention"] == 960000
    assert uploads[0]["filename"] != path.name
    assert uploads[0]["filename"].endswith(".bin")
    assert max(len(base64.b64decode(p["chunk_data"])) for p in uploads[:-1]) <= 65536
    assert napcat.requests[-1]["params"]["message"][0]["data"] == {
        "file": napcat.remote_path,
        "thumb": napcat.remote_path,
    }
    if size > 65536:
        assert uploads[0]["chunk_data"] not in caplog.text


@pytest.mark.parametrize(
    "action",
    [
        "send_group_msg",
        "send_private_msg",
        "send_forward_msg",
        "send_private_forward_msg",
    ],
)
async def test_all_media_nested_cq_and_originals(tmp_path: Path, action: str) -> None:
    path = tmp_path / "中 文,[x]&.png"
    path.write_bytes(b"file bytes")
    napcat = NapCat()
    transport = OneBotFileTransport(napcat.respond, chunk_size=3)
    escaped = (
        str(path)
        .replace("&", "&amp;")
        .replace("[", "&#91;")
        .replace("]", "&#93;")
        .replace(",", "&#44;")
    )
    segments: list[dict[str, Any]] = [
        {"type": kind, "data": {"file": path.as_uri()}}
        for kind in ("image", "record", "video", "file")
    ]
    segments += [
        {
            "type": "node",
            "data": {
                "content": [
                    {
                        "type": "node",
                        "data": {
                            "content": f"原文 [CQ:image,file={escaped}] [CQ:unknown,file={escaped}]"
                        },
                    }
                ]
            },
        }
    ]
    segments += [
        {"type": "text", "data": {"text": str(path)}},
        {"type": "unknown", "data": {"file": str(path)}},
    ]
    params = {"messages" if "forward" in action else "message": segments}
    original = deepcopy(params)
    async with transport.prepare(action, params) as prepared:
        converted = prepared.apply(action, params)
    assert params == original
    assert len(napcat.completed) == 1
    result = next(iter(converted.values()))
    for segment in result[:4]:
        assert segment["data"]["file"] == napcat.remote_path
    assert napcat.remote_path in result[4]["data"]["content"][0]["data"]["content"]
    assert result[-2:] == segments[-2:]
    assert (
        f"[CQ:unknown,file={escaped}]"
        in result[4]["data"]["content"][0]["data"]["content"]
    )


@pytest.mark.parametrize(
    "source",
    [
        "https://example.org/a.png",
        "http://host/a?token=test",
        "base64://AA==",
        "data:image/png;base64,AA==",
        "ABCDEF123.image",
        "123456",
    ],
)
async def test_remote_sources_passthrough(source: str) -> None:
    call = AsyncMock()
    transport = OneBotFileTransport(call)
    params = {"message": f"[CQ:image,file={source}]"}
    async with transport.prepare("send_group_msg", params) as prepared:
        assert prepared.apply("send_group_msg", params) == params
    call.assert_not_called()


async def test_local_does_no_io_or_transfer(tmp_path: Path) -> None:
    call = AsyncMock()
    transport = OneBotFileTransport(
        call, config_getter=lambda: FileSendSettings("local")
    )
    params = {"file": (tmp_path / "does-not-exist.zip").as_uri()}
    async with transport.prepare("upload_group_file", params) as prepared:
        assert prepared.apply("upload_group_file", params) == params
    call.assert_not_called()


@pytest.mark.parametrize(
    "failure,match",
    [
        ("unsupported", "onebot.file_send_mode"),
        ("network", "连接中断"),
        ("ack", "分块数量"),
        ("hash", "SHA-256"),
        ("reset_failure", "分块数量"),
    ],
)
async def test_prepare_errors_never_send_or_fallback(
    tmp_path: Path, failure: str, match: str
) -> None:
    path = tmp_path / "data.txt"
    path.write_bytes(b"hello")
    napcat = NapCat()
    napcat.failure = failure
    client = OneBotClient(
        "ws://unused", file_transport=OneBotFileTransport(napcat.respond)
    )
    client._call_api_raw = AsyncMock()  # type: ignore[method-assign]
    async with RequestContext(request_type="group", group_id=1, sender_id=2) as ctx:
        with pytest.raises(FileTransferError, match=match):
            await client.upload_group_file(1, str(path))
        assert not was_message_sent(ctx)
    client._call_api_raw.assert_not_called()
    reset = [r for r in napcat.requests if r["params"].get("reset")]
    assert bool(reset) == (failure not in {"unsupported", "hash"})


async def test_empty_file_fails_before_upload(tmp_path: Path) -> None:
    path = tmp_path / "empty"
    path.touch()
    call = AsyncMock()
    transport = OneBotFileTransport(call)
    with pytest.raises(FileTransferError, match="零字节"):
        async with transport.prepare("upload_private_file", {"file": str(path)}):
            pytest.fail("must not prepare")
    call.assert_not_called()


async def test_source_change_prevents_completion(tmp_path: Path) -> None:
    path = tmp_path / "source"
    path.write_bytes(b"123456")
    napcat = NapCat()

    async def mutate(action: str, params: dict[str, Any]) -> dict[str, Any]:
        result = await napcat.respond(action, params)
        if "chunk_data" in params:
            path.write_bytes(b"changed")
        return result

    transport = OneBotFileTransport(mutate, chunk_size=3)
    with pytest.raises(FileTransferError, match="源文件发生变化"):
        async with transport.prepare("upload_private_file", {"file": str(path)}):
            pytest.fail("must not prepare")
    assert not napcat.completed
    assert napcat.requests[-1]["params"]["reset"] is True


async def test_fallback_reuses_upload_and_original_idempotence(tmp_path: Path) -> None:
    path = tmp_path / "archive.zip"
    path.write_bytes(b"archive")
    napcat = NapCat()
    napcat.failure = "fallback"
    client = OneBotClient(
        "ws://unused", file_transport=OneBotFileTransport(napcat.respond)
    )
    client._call_api_raw = napcat.respond  # type: ignore[method-assign]
    await client.upload_private_file(1, str(path), "展示.zip")
    assert len(napcat.completed) == 1
    assert [r["action"] for r in napcat.requests[-2:]] == [
        "upload_private_file",
        "send_private_msg",
    ]
    primary, fallback = napcat.requests[-2:]
    assert primary["params"]["file"] == fallback["params"]["message"][0]["data"]["file"]
    assert fallback["params"]["message"][0]["data"]["name"] == "展示.zip"


async def test_uncertain_forward_blocks_reupload(tmp_path: Path) -> None:
    path = tmp_path / "video.mp4"
    path.write_bytes(b"video")
    napcat = NapCat()
    napcat.failure = "delivery_timeout"
    client = OneBotClient(
        "ws://unused", file_transport=OneBotFileTransport(napcat.respond)
    )
    client._call_api_raw = napcat.respond  # type: ignore[method-assign]
    nodes = [
        {
            "type": "node",
            "data": {"content": [{"type": "video", "data": {"file": str(path)}}]},
        }
    ]
    async with RequestContext(request_type="group", group_id=1, sender_id=2) as ctx:
        for _ in range(2):
            with pytest.raises(OneBotDeliveryUncertainError):
                await client.send_forward_msg(1, nodes)
        assert was_message_sent(ctx)
    assert len(napcat.completed) == 1
    assert len([r for r in napcat.requests if r["action"] == "send_forward_msg"]) == 1


async def test_cancel_and_budget_reset_only_current_stream(tmp_path: Path) -> None:
    path = tmp_path / "data"
    path.write_bytes(b"abc")
    for cancel in (False, True):
        napcat = NapCat()
        napcat.failure = "blocked"
        transport = OneBotFileTransport(
            napcat.respond, timeout=0.03 if not cancel else 10
        )

        async def prepare() -> None:
            async with transport.prepare("upload_group_file", {"file": str(path)}):
                pytest.fail("must not send")

        task = asyncio.create_task(prepare())
        await napcat.received.wait()
        if cancel:
            task.cancel()
        with pytest.raises(asyncio.CancelledError if cancel else FileTransferError):
            await task
        assert napcat.requests[-1]["params"]["reset"] is True
        assert (
            napcat.requests[-1]["params"]["stream_id"]
            == napcat.requests[0]["params"]["stream_id"]
        )


async def test_hot_reload_snapshot_queue_and_text_bypass(tmp_path: Path) -> None:
    path = tmp_path / "data"
    path.write_bytes(b"abc")
    cfg = SimpleNamespace(
        onebot_file_send_mode="stream", onebot_file_send_host="127.0.0.1"
    )
    napcat = NapCat()
    napcat.failure = "blocked"
    transport = OneBotFileTransport(napcat.respond, config_getter=lambda: cfg)

    async def prepare() -> dict[str, Any]:
        async with transport.prepare("upload_group_file", {"file": str(path)}) as files:
            return files.apply("upload_group_file", {"file": str(path)})

    first = asyncio.create_task(prepare())
    await napcat.received.wait()
    queued = asyncio.create_task(prepare())
    await asyncio.sleep(0)
    assert len(napcat.requests) == 1
    async with transport.prepare("send_group_msg", {"message": "text"}):
        pass
    cfg.onebot_file_send_mode = "local"
    assert await prepare() == {"file": str(path)}
    napcat.block.set()
    assert (await first)["file"] == napcat.remote_path
    assert (await queued)["file"] == napcat.remote_path
    assert len(napcat.completed) == 2
    assert len({r["params"]["filename"] for r in napcat.requests}) == 2


async def test_duplicate_and_late_echo_ignored() -> None:
    client = OneBotClient("ws://unused")
    future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
    client._pending_responses["x"] = future
    future.cancel()
    await client._dispatch_message({"echo": "x"})
    await client._dispatch_message({"echo": "unknown"})
    done: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
    client._pending_responses["y"] = done
    await client._dispatch_message({"echo": "y", "data": 1})
    await client._dispatch_message({"echo": "y", "data": 2})
    assert done.result()["data"] == 1


def test_logging_redacts_upload_and_file_token() -> None:
    safe = json.dumps(
        sanitize_data(
            {
                "chunk_data": "ABCDEF",
                "file": "http://host/api/v1/onebot/files/a?token=SECRET",
                "Authorization": "Bearer AUTH",
            }
        )
    )
    assert "ABCDEF" not in safe and "SECRET" not in safe and "AUTH" not in safe
    assert "CHUNK" not in str(sanitize_data('{"chunk_data": "CHUNK"}'))


async def test_websocket_debug_does_not_leak_frames_or_auth(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    source = tmp_path / "file"
    content = b"private-file-payload"
    source.write_bytes(content)
    caplog.set_level(logging.DEBUG)
    async with connected(NapCat(), token="private-onebot-token") as client:
        await client.upload_group_file(1, str(source))
    assert base64.b64encode(content).decode() not in caplog.text
    assert "private-onebot-token" not in caplog.text


def test_cq_replacement_does_not_touch_text() -> None:
    params = {"message": "ordinary /path [CQ:unknown,file=/path] [CQ:image,file=/path]"}
    assert (
        map_file_references("send_group_msg", params, lambda _: "/remote")["message"]
        == "ordinary /path [CQ:unknown,file=/path] [CQ:image,file=/remote]"
    )


@pytest.mark.parametrize(
    "message",
    [
        "[CQ:image]",
        "[CQ:record,cache=0]",
        "[CQ:video,file=base64://AA==]",
        "[CQ:unknown]",
    ],
)
def test_unmodified_cq_keeps_exact_format(message: str) -> None:
    params = {"message": message}
    assert (
        map_file_references("send_group_msg", params, lambda source: source) == params
    )


def test_file_segment_preserves_implicit_display_name() -> None:
    params = {
        "message": [
            {"type": "file", "data": {"file": "file:///tmp/%E4%B8%AD%E6%96%87.txt"}}
        ]
    }
    result = map_file_references(
        "send_group_msg", params, lambda _: "/napcat/random.txt"
    )
    assert result["message"][0]["data"]["name"] == "中文.txt"
    cq = map_file_references(
        "send_group_msg",
        {"message": "[CQ:file,file=/tmp/demo.txt]"},
        lambda _: "/napcat/random.txt",
    )
    assert "name=demo.txt" in cq["message"]


@pytest.mark.parametrize(
    "failure", ["disconnect_upload", "disconnect_send", "unsupported"]
)
async def test_real_websocket_failure_phase(tmp_path: Path, failure: str) -> None:
    source = tmp_path / "file"
    source.write_bytes(b"data")
    napcat = NapCat()
    napcat.failure = failure
    async with connected(napcat) as client:
        async with RequestContext(request_type="group", group_id=1, sender_id=2) as ctx:
            expected = (
                OneBotDeliveryUncertainError
                if failure == "disconnect_send"
                else FileTransferError
            )
            with pytest.raises(expected):
                await asyncio.wait_for(
                    client.upload_group_file(1, str(source)), timeout=2
                )
            assert was_message_sent(ctx) == (failure == "disconnect_send")


@pytest.mark.parametrize("cancel", [True, False])
async def test_real_send_cancellation_and_total_budget_are_uncertain(
    tmp_path: Path, cancel: bool
) -> None:
    source = tmp_path / "file"
    source.write_bytes(b"data")
    napcat = NapCat()
    napcat.failure = "send_blocked"
    async with connected(napcat) as client:
        client.file_transport.timeout = 0.3 if not cancel else 10
        async with RequestContext(request_type="group", group_id=1, sender_id=2) as ctx:
            task = asyncio.create_task(client.upload_group_file(1, str(source)))
            await asyncio.wait_for(napcat.received.wait(), timeout=2)
            if cancel:
                task.cancel()
            with pytest.raises(OneBotDeliveryUncertainError):
                await asyncio.wait_for(task, timeout=2)
            assert was_message_sent(ctx)
    assert len(napcat.completed) == 1
    assert not any(r["params"].get("reset") for r in napcat.requests)


async def test_cancelled_queue_and_queue_wait_outside_budget(tmp_path: Path) -> None:
    path = tmp_path / "data"
    path.write_bytes(b"abc")
    napcat = NapCat()
    transport = OneBotFileTransport(napcat.respond, timeout=0.1)
    await transport._stream_lock.acquire()

    async def prepare() -> None:
        async with transport.prepare("upload_group_file", {"file": str(path)}):
            pass

    cancelled = asyncio.create_task(prepare())
    queued = asyncio.create_task(prepare())
    await asyncio.sleep(0.12)
    assert not napcat.requests
    cancelled.cancel()
    with pytest.raises(asyncio.CancelledError):
        await cancelled
    transport._stream_lock.release()
    await queued
    assert len(napcat.completed) == 1


@pytest.mark.parametrize("remote_path", ["/app/napcat/temp/data", r"D:\temp\data"])
async def test_remote_completion_path_is_not_read_on_bot(
    tmp_path: Path, remote_path: str
) -> None:
    source = tmp_path / "file"
    source.write_bytes(b"data")
    napcat = NapCat()
    napcat.remote_path = remote_path
    transport = OneBotFileTransport(napcat.respond)
    async with transport.prepare("upload_group_file", {"file": str(source)}) as files:
        assert (
            files.apply("upload_group_file", {"file": str(source)})["file"]
            == remote_path
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("type", "stream"),
        ("received_chunks", 0),
        ("total_chunks", 2),
        ("file_size", 0),
        ("file_path", "relative"),
        ("file_path", ""),
        ("sha256", None),
    ],
)
async def test_malformed_completion_never_sends(
    tmp_path: Path, field: str, value: Any
) -> None:
    source = tmp_path / "file"
    source.write_bytes(b"data")
    napcat = NapCat()

    async def corrupt(action: str, params: dict[str, Any]) -> dict[str, Any]:
        response = await napcat.respond(action, params)
        if params.get("is_complete"):
            response["data"][field] = value
        return response

    transport = OneBotFileTransport(corrupt)
    with pytest.raises(FileTransferError):
        async with transport.prepare("upload_group_file", {"file": str(source)}):
            pytest.fail("must not send")


async def test_only_incomplete_second_file_is_reset(tmp_path: Path) -> None:
    first, second = tmp_path / "first.txt", tmp_path / "second.txt"
    first.write_bytes(b"one")
    second.write_bytes(b"two")
    napcat = NapCat()

    async def fail_second(action: str, params: dict[str, Any]) -> dict[str, Any]:
        if napcat.completed:
            napcat.failure = "ack"
        return await napcat.respond(action, params)

    transport = OneBotFileTransport(fail_second)
    params = {
        "message": [
            {"type": "image", "data": {"file": str(p)}} for p in (first, second)
        ]
    }
    with pytest.raises(FileTransferError):
        async with transport.prepare("send_group_msg", params):
            pytest.fail("must not send")
    assert len(napcat.completed) == 1
    resets = [r for r in napcat.requests if r["params"].get("reset")]
    assert len(resets) == 1
    assert resets[0]["params"]["stream_id"] not in napcat.completed


@pytest.mark.parametrize(
    "entrypoint",
    ["group_file", "private_file", "group_image", "private_record", "forward_video"],
)
async def test_sender_history_registers_original_local_source(
    tmp_path: Path, entrypoint: str
) -> None:
    source = tmp_path / "原始文件.png"
    source.write_bytes(b"media")
    napcat = NapCat()
    client = OneBotClient(
        "ws://unused", file_transport=OneBotFileTransport(napcat.respond)
    )
    client._call_api_raw = napcat.respond  # type: ignore[method-assign]
    registry = AttachmentRegistry(
        registry_path=tmp_path / "registry.json", cache_dir=tmp_path / "attachments"
    )
    register = AsyncMock(wraps=registry.register_local_file)
    registry.register_local_file = register  # type: ignore[method-assign]
    history: Any = SimpleNamespace(
        add_group_message=AsyncMock(), add_private_message=AsyncMock()
    )
    cfg = MagicMock()
    cfg.is_group_allowed.return_value = True
    cfg.is_private_allowed.return_value = True
    sender = MessageSender(
        client, history, bot_qq=99, config=cfg, attachment_registry=registry
    )
    if entrypoint == "group_file":
        await sender.send_group_file(1, str(source), "展示.png")
    elif entrypoint == "private_file":
        await sender.send_private_file(1, str(source), "展示.png")
    elif entrypoint == "group_image":
        await sender.send_group_message(1, f"[CQ:image,file={source.as_uri()}]")
    elif entrypoint == "private_record":
        await sender.send_private_message(1, f"[CQ:record,file={source.as_uri()}]")
    else:
        await sender.send_group_forward_message(
            1,
            [
                {
                    "type": "node",
                    "data": {
                        "content": [
                            {"type": "video", "data": {"file": source.as_uri()}}
                        ]
                    },
                }
            ],
            history_message="Bilibili 视频",
        )
    assert register.await_count == 1
    call = register.await_args
    assert call is not None
    assert str(source) in str(call)
    assert napcat.remote_path not in str(call)
    history_call = (
        history.add_private_message
        if entrypoint.startswith("private")
        else history.add_group_message
    ).await_args
    assert history_call is not None
    assert history_call.kwargs["attachments"]
    assert napcat.remote_path not in str(history_call)
    assert len(napcat.completed) == 1
