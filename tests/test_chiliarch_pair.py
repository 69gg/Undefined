"""配对只发布私有凭证文件，不依赖主配置，也不消耗未完成配对。"""

from __future__ import annotations

import importlib
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest

from Undefined.chiliarch.pair import pair
from Undefined.config import Config
from Undefined.config.env_registry import ENV_REGISTRY

native = importlib.import_module("chiliarch.client")


async def test_native_pair_publishes_complete_identity_without_reading_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    config = tmp_path / "config.toml"
    example = tmp_path / "config.toml.example"
    original = b"# deliberate invalid TOML: pairing must not parse or change this\n["
    config.write_bytes(original)
    example.write_bytes(original)
    state = tmp_path / "data" / "chiliarch" / "client.db"
    state.parent.mkdir(parents=True)
    Path(f"{state}-wal").write_bytes(b"orphaned old WAL")
    Path(f"{state}-shm").write_bytes(b"orphaned old shared memory")

    def platform(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/agent/pair"
        assert not state.exists()
        assert not Path(f"{state}-wal").exists()
        assert not Path(f"{state}-shm").exists()
        return httpx.Response(
            200, json={"agent_id": "paired-agent", "credential": "test-only"}
        )

    http = httpx.AsyncClient(transport=httpx.MockTransport(platform))
    monkeypatch.setattr(native.httpx, "AsyncClient", lambda: http)
    await pair("https://platform.invalid", "code", "Undefined", "host", state, "介绍")
    assert config.read_bytes() == original and example.read_bytes() == original
    store = native.ClientStore(state)
    await store.open()
    try:
        identity = await store.identity()
        assert identity["credential"] == "test-only"
        assert identity["agent_id"] == "paired-agent"
        assert identity["server_url"] == "https://platform.invalid"
        assert identity["introduction"] == "介绍"
    finally:
        await store.close()
    assert not list(state.parent.glob("*.pairing*"))


async def test_failed_pair_does_not_enable_channel_or_leave_partial_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = tmp_path / "client.db"

    async def fail(*args: object, **kwargs: object) -> None:
        pending = args[4]
        assert isinstance(pending, Path)
        pending.write_bytes(b"partial")
        Path(f"{pending}-wal").write_bytes(b"partial")
        Path(f"{pending}-shm").write_bytes(b"partial")
        raise RuntimeError("credential=secret")

    monkeypatch.setattr(native.AgentClient, "pair", AsyncMock(side_effect=fail))
    with pytest.raises(RuntimeError):
        await pair(
            "https://platform.invalid", "code", "Undefined", "host", state, "介绍"
        )
    assert not state.exists()
    assert not list(tmp_path.glob("*.pairing*"))


async def test_publish_failure_keeps_redeemed_database_and_sidecars(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    module = importlib.import_module("Undefined.chiliarch.pair")
    state = tmp_path / "client.db"
    pending: Path | None = None

    async def exchange(*args: object, **kwargs: object) -> None:
        nonlocal pending
        assert isinstance(args[4], Path)
        pending = args[4]
        pending.write_bytes(b"redeemed-secret")
        Path(f"{pending}-wal").write_bytes(b"credential WAL")
        Path(f"{pending}-shm").write_bytes(b"credential shared memory")

    monkeypatch.setattr(native.AgentClient, "pair", AsyncMock(side_effect=exchange))
    monkeypatch.setattr(module.io, "move_path", AsyncMock(side_effect=OSError("full")))
    with pytest.raises(OSError, match="full"):
        await pair(
            "https://platform.invalid", "code", "Undefined", "host", state, "介绍"
        )
    assert not state.exists()
    assert pending is not None
    assert pending.read_bytes() == b"redeemed-secret"
    assert Path(f"{pending}-wal").read_bytes() == b"credential WAL"
    assert Path(f"{pending}-shm").read_bytes() == b"credential shared memory"
    assert str(pending) in caplog.text
    assert "redeemed-secret" not in caplog.text


async def test_existing_pair_file_is_rejected_before_prompting_or_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = importlib.import_module("Undefined.chiliarch.pair")
    prompt = AsyncMock(side_effect=AssertionError("must not ask for another code"))
    operation = AsyncMock()
    monkeypatch.setattr(module.getpass, "getpass", prompt)
    monkeypatch.setattr(native.AgentClient, "pair", operation)
    state = tmp_path / "client.db"
    state.write_bytes(b"original")
    with pytest.raises(ValueError, match="state 已存在"):
        await pair("https://platform.invalid", None, "Undefined", "host", state, "介绍")
    assert state.read_bytes() == b"original"
    prompt.assert_not_called()
    operation.assert_not_awaited()


async def test_cancelling_pair_preserves_redeemed_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = tmp_path / "client.db"
    redeemed = asyncio.Event()
    release = asyncio.Event()

    async def exchange(*args: object, **kwargs: object) -> None:
        pending = args[4]
        assert isinstance(pending, Path)
        pending.write_bytes(b"redeemed credential")
        redeemed.set()
        await release.wait()

    monkeypatch.setattr(native.AgentClient, "pair", AsyncMock(side_effect=exchange))
    task = asyncio.create_task(
        pair("https://platform.invalid", "code", "Undefined", "host", state, "介绍")
    )
    await redeemed.wait()
    task.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert state.read_bytes() == b"redeemed credential"
    assert not list(tmp_path.glob("*.pairing*"))


def test_cli_uses_detected_default_path_without_config_flags(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    module = importlib.import_module("Undefined.chiliarch.pair")
    state = tmp_path / "client.db"
    operation = AsyncMock()
    monkeypatch.setattr(module, "DEFAULT_STATE_PATH", state)
    monkeypatch.setattr(module, "pair", operation)
    monkeypatch.setattr(
        "sys.argv", ["Undefined-chiliarch-pair", "--server", "https://platform.invalid"]
    )
    module.run()
    operation.assert_awaited_once()
    assert operation.call_args.args[1] is None
    assert operation.call_args.args[4] == state
    assert "无需修改配置" in capsys.readouterr().out


def test_no_main_config_or_environment_switch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHILIARCH_ENABLED", "true")
    cfg = Config.from_mapping({"chiliarch": {"enabled": True}}, strict=False)
    assert not hasattr(cfg, "chiliarch")
    assert not any(path[0] == "chiliarch" for path in ENV_REGISTRY)
