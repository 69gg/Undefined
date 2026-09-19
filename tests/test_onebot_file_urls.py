from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

from aiohttp import ClientSession, web
import pytest

from Undefined.api import RuntimeAPIServer
from Undefined.api._context import RuntimeAPIContext
from Undefined.api._openapi import _build_openapi_spec
from Undefined.config.models import APIConfig
from Undefined.onebot.client import OneBotClient
from Undefined.onebot.file_errors import FileTransferError
from Undefined.onebot.file_store import OneBotFileStore
from Undefined.onebot.file_transport import OneBotFileTransport


class Clock:
    def __init__(self) -> None:
        self.now = 2000000000.0

    def __call__(self) -> float:
        return self.now


def context(cfg: Any, client: OneBotClient) -> RuntimeAPIContext:
    return RuntimeAPIContext(
        config_getter=lambda: cfg,
        onebot=client,
        ai=SimpleNamespace(),
        command_dispatcher=None,
        queue_manager=None,
        history_manager=None,
    )


@asynccontextmanager
async def runtime(
    tmp_path: Path,
) -> AsyncIterator[tuple[RuntimeAPIServer, OneBotFileStore, OneBotClient, Any, Clock]]:
    clock = Clock()
    cfg = SimpleNamespace(
        api=APIConfig(auth_key="API-KEY"),
        onebot_file_send_mode="url",
        onebot_file_send_host="127.0.0.1",
    )
    store = OneBotFileStore(tmp_path / "cache", clock=clock)
    client = OneBotClient("ws://unused", config_getter=lambda: cfg)
    client.file_transport.store = store
    server = RuntimeAPIServer(context(cfg, client), "127.0.0.1", 0)
    await server.start()
    try:
        yield server, store, client, cfg, clock
    finally:
        await server.stop()


async def test_get_head_range_tokens_source_cleanup_mode_and_actual_port(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    source = tmp_path / "中文 文件.txt"
    source.write_bytes(b"0123456789")
    caplog.set_level("DEBUG")
    async with runtime(tmp_path) as (_, store, client, cfg, clock):
        sender = AsyncMock(return_value={"status": "ok"})
        client._call_api_raw = sender  # type: ignore[method-assign]
        cfg.api.port = 9  # 未重启时新配置不能影响实际下载端口。
        await client.upload_group_file(1, str(source), "展示名称.txt")
        sent = sender.await_args_list[0].args[1]
        assert sent["name"] == "展示名称.txt"
        url = sent["file"]
        assert urlsplit(url).port == store.port and store.port != 9
        token = parse_qs(urlsplit(url).query)["token"][0]
        base = url.split("?", 1)[0]
        source.unlink()
        cfg.onebot_file_send_mode = "local"
        async with ClientSession() as http:
            for _ in range(2):
                async with http.get(url) as response:
                    assert response.status == 200
                    assert await response.read() == b"0123456789"
                    assert (
                        "filename*=UTF-8''" in response.headers["Content-Disposition"]
                    )
                    assert response.headers["X-Content-Type-Options"] == "nosniff"
            async with http.head(url) as response:
                assert response.status == 200
                assert response.content_length == 10
                assert await response.read() == b""
            async with http.get(url, headers={"Range": "bytes=2-5"}) as response:
                assert response.status == 206
                assert await response.read() == b"2345"
            for bad_url in (base, f"{base}?token=wrong"):
                async with http.get(bad_url) as response:
                    assert response.status == 401
            async with http.get(
                f"http://127.0.0.1:{store.port}/api/v1/probes/internal?token={token}"
            ) as response:
                assert response.status == 401
            async with http.get(f"{base}-missing?token={token}") as response:
                assert response.status == 404
            clock.now += 960
            async with http.get(url) as response:
                assert response.status == 404
        await store.cleanup()
        assert not list((tmp_path / "cache").iterdir())
    # 对其他 API 携带 token 的请求也不应泄露查询令牌。
    assert token not in caplog.text


async def test_tokens_are_per_file_and_ipv6_format(tmp_path: Path) -> None:
    source = tmp_path / "file"
    source.write_bytes(b"abc")
    store = OneBotFileStore(tmp_path / "cache")
    await store.start(12345)
    try:
        first = await store.publish(source, "::1")
        second = await store.publish(source, "::1")
        assert first.startswith("http://[::1]:12345/")
        first_token = parse_qs(urlsplit(first).query)["token"][0]
        second_id = urlsplit(second).path.rsplit("/", 1)[1]
        from Undefined.onebot.file_store import FileAuthorizationError

        with pytest.raises(FileAuthorizationError) as exc:
            async with store.acquire(second_id, first_token):
                pytest.fail("token must not authorize another file")
        assert exc.value.status == 401
    finally:
        await store.stop()


async def test_expiry_keeps_in_progress_download_alive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "large.bin"
    source.write_bytes(b"test payload" * 1000)
    entered = asyncio.Event()
    release = asyncio.Event()
    real_prepare = web.FileResponse.prepare

    async def slow_prepare(self: web.FileResponse, request: web.Request) -> Any:
        entered.set()
        await release.wait()
        return await real_prepare(self, request)

    monkeypatch.setattr(web.FileResponse, "prepare", slow_prepare)
    async with runtime(tmp_path) as (_, store, _, _, clock):
        url = await store.publish(source, "127.0.0.1")
        async with ClientSession() as http:

            async def read() -> bytes:
                async with http.get(url) as response:
                    assert response.status == 200
                    return await response.read()

            task = asyncio.create_task(read())
            await entered.wait()
            clock.now += 961
            await store.cleanup()
            assert list((tmp_path / "cache").iterdir())
            async with http.get(url) as response:
                assert response.status == 404
            release.set()
            assert await task == source.read_bytes()
        # 读者退出之后立即释放过期副本。
        await store.cleanup()
        assert not store._files


async def test_unready_runtime_preparation_error(tmp_path: Path) -> None:
    source = tmp_path / "data"
    source.write_bytes(b"data")
    store = OneBotFileStore(tmp_path / "cache")
    transport = OneBotFileTransport(
        AsyncMock(),
        config_getter=lambda: SimpleNamespace(onebot_file_send_mode="url"),
        store=store,
    )
    with pytest.raises(FileTransferError, match="Runtime 文件服务未就绪"):
        async with transport.prepare("upload_group_file", {"file": str(source)}):
            pytest.fail("must not send")
    assert not (tmp_path / "cache").exists()


async def test_runtime_start_failure_does_not_publish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = OneBotFileStore(tmp_path / "cache")
    cfg = SimpleNamespace(api=APIConfig(auth_key="key"))
    client = OneBotClient("ws://unused")
    server = RuntimeAPIServer(context(cfg, client), "127.0.0.1", 0, file_store=store)
    monkeypatch.setattr(
        web.TCPSite, "start", AsyncMock(side_effect=OSError("bind failed"))
    )
    with pytest.raises(OSError, match="bind failed"):
        await server.start()
    assert store.port is None
    assert server._runner is None


async def test_start_prunes_only_expired_module_cache_and_stop_owns_its_files(
    tmp_path: Path,
) -> None:
    clock = Clock()
    cache = tmp_path / "cache"
    cache.mkdir()
    expired = cache / f"onebot-{int((clock.now - 1) * 1000)}-{uuid4().hex}"
    active = cache / f"onebot-{int((clock.now + 1000) * 1000)}-{uuid4().hex}"
    unrelated = cache / "unrelated"
    for directory in (expired, active, unrelated):
        directory.mkdir()
        (directory / "content").write_bytes(b"data")
    store = OneBotFileStore(cache, clock=clock)
    await store.start(12345)
    assert not expired.exists() and active.exists() and unrelated.exists()
    source = tmp_path / "file"
    source.write_bytes(b"data")
    await store.publish(source, "localhost")
    await store.stop()
    assert set(cache.iterdir()) == {active, unrelated}


async def test_url_host_snapshot_during_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from Undefined.utils import io

    source = tmp_path / "data"
    source.write_bytes(b"data")
    original_copy = io.copy_file_atomic
    async with runtime(tmp_path) as (_, store, client, cfg, _):

        async def copy(source: Path, target: Path, chunk_size: int) -> None:
            cfg.onebot_file_send_host = "new.example"
            await original_copy(source, target, chunk_size)

        monkeypatch.setattr(io, "copy_file_atomic", copy)
        async with client.file_transport.prepare(
            "upload_group_file", {"file": str(source)}
        ) as files:
            first = files.apply("upload_group_file", {"file": str(source)})["file"]
        async with client.file_transport.prepare(
            "upload_group_file", {"file": str(source)}
        ) as files:
            second = files.apply("upload_group_file", {"file": str(source)})["file"]
        assert urlsplit(first).hostname == "127.0.0.1"
        assert urlsplit(second).hostname == "new.example"
        assert len(store._files) == 2


def test_openapi_file_token_scope() -> None:
    from aiohttp.test_utils import make_mocked_request

    cfg = SimpleNamespace(api=APIConfig())
    spec = _build_openapi_spec(
        context(cfg, OneBotClient("ws://unused")),
        make_mocked_request("GET", "/openapi.json", headers={"Host": "localhost"}),
    )
    route = spec["paths"]["/api/v1/onebot/files/{file_id}"]
    assert set(route) == {"get", "head"}
    assert route["get"]["security"] == [{"OneBotFileToken": []}]
    assert spec["security"] == [{"ApiKeyAuth": []}]


async def test_text_file_tool_cleanup_preserves_published_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from Undefined.skills.toolsets.messages.send_text_file.handler import execute

    monkeypatch.chdir(tmp_path)
    async with runtime(tmp_path) as (_, _, client, _, _):
        send = AsyncMock(return_value={"status": "ok"})
        client._call_api_raw = send  # type: ignore[method-assign]
        ctx: dict[str, Any] = {
            "request_type": "group",
            "group_id": 1,
            "sender": SimpleNamespace(send_group_file=client.upload_group_file),
        }
        result = await execute({"filename": "说明.txt", "content": "保留文件内容"}, ctx)
        assert "文件已发送" in result
        assert not list((tmp_path / "data/cache/text_files").rglob("说明.txt"))
        assert ctx["message_sent_this_turn"] is True
        url = send.await_args_list[0].args[1]["file"]
        async with ClientSession() as http:
            async with http.get(url) as response:
                assert await response.text() == "保留文件内容"


async def test_text_file_tool_exposes_preparation_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from Undefined.skills.toolsets.messages.send_text_file.handler import execute

    monkeypatch.chdir(tmp_path)
    error = FileTransferError("stream", "请切换 onebot.file_send_mode")
    send = AsyncMock(side_effect=error)
    ctx: dict[str, Any] = {
        "request_type": "group",
        "group_id": 1,
        "sender": SimpleNamespace(send_group_file=send),
    }
    assert (
        await execute({"filename": "说明.txt", "content": "文件内容"}, ctx)
        == error.user_message
    )
    assert not ctx.get("message_sent_this_turn")
    assert not list((tmp_path / "data/cache/text_files").rglob("说明.txt"))


@pytest.mark.parametrize("fail", [False, True])
async def test_url_file_tool_cleanup_and_error_feedback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fail: bool
) -> None:
    from Undefined.skills.toolsets.messages.send_url_file import handler
    from Undefined.utils import io

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        handler,
        "probe_remote_file",
        AsyncMock(
            return_value=SimpleNamespace(
                content_length=6, final_url="https://example.org/file.txt", headers={}
            )
        ),
    )

    async def download(**kwargs: Any) -> tuple[str, int]:
        path = Path(kwargs["target_path"])
        await io.write_bytes(path, b"remote")
        return str(path.resolve()), 6

    monkeypatch.setattr(handler, "_download_to_local_file", download)
    async with runtime(tmp_path) as (_, _, client, _, _):
        send = AsyncMock(return_value={"status": "ok"})
        client._call_api_raw = send  # type: ignore[method-assign]
        error = FileTransferError("stream", "请切换 onebot.file_send_mode")
        file_send = AsyncMock(side_effect=error) if fail else client.upload_group_file
        ctx: dict[str, Any] = {
            "request_type": "group",
            "group_id": 1,
            "sender": SimpleNamespace(send_group_file=file_send),
        }
        result = await handler.execute(
            {"url": "https://example.org/file.txt", "filename": "file.txt"}, ctx
        )
        assert not list((tmp_path / "data/cache/url_files").rglob("file.txt"))
        if fail:
            assert result == error.user_message
            assert not ctx.get("message_sent_this_turn")
            send.assert_not_awaited()
        else:
            assert "文件已发送" in result
            async with ClientSession() as http:
                async with http.get(
                    send.await_args_list[0].args[1]["file"]
                ) as response:
                    assert await response.read() == b"remote"
