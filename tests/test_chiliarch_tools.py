from __future__ import annotations

import importlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from aiohttp.test_utils import TestClient, TestServer

from Undefined.api import RuntimeAPIContext, RuntimeAPIServer
from Undefined.chiliarch import ChiliarchService
from Undefined.chiliarch.pair import pair
from Undefined.config import Config
from Undefined.skills.toolsets.chiliarch.call.handler import execute


async def test_tool_passes_origin_and_retains_pending_request_id() -> None:
    response = {"status": "pending", "request_id": "stable"}
    service = SimpleNamespace(invoke=AsyncMock(return_value=response))
    context = {"address": "wechat:123", "chiliarch_service": service}
    arguments = {"request_id": "stable"}
    result = await execute({"action": "get_result", "arguments": arguments}, context)
    assert json.loads(result) == response
    service.invoke.assert_awaited_once_with("get_result", arguments, context)
    assert await execute({"action": "status"}, {}) == "chiliarch 渠道未启用"
    service.invoke.side_effect = RuntimeError("credential=secret")
    assert "secret" not in await execute({"action": "status"}, context)


async def test_damaged_installation_does_not_break_other_channels(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = importlib.import_module

    def missing(name: str, package: str | None = None) -> Any:
        if name.startswith("chiliarch."):
            raise ModuleNotFoundError(name)
        return original(name, package)

    monkeypatch.setattr(importlib, "import_module", missing)
    state = tmp_path / "client.db"
    state.touch()
    service = ChiliarchService(SimpleNamespace(), state_path=state)
    await service.start()
    assert service.status()["reason"] == "ModuleNotFoundError"
    assert not service.status()["mailbox_ready"]
    await service.stop()


async def test_pair_reuses_native_credentials_and_never_declares_workdir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    native = importlib.import_module("chiliarch.client")
    state = tmp_path / "new.db"

    async def persist(*args: Any, **kwargs: Any) -> None:
        assert not state.exists()
        args[4].write_bytes(b"paired credential")

    operation = AsyncMock(side_effect=persist)
    monkeypatch.setattr(native.AgentClient, "pair", operation)
    await pair(
        "http://example.invalid",
        "test-code",
        "Undefined",
        "test-machine",
        state,
        "介绍",
    )
    operation.assert_awaited_once()
    assert operation.call_args.args[4] != state
    assert state.read_bytes() == b"paired credential"
    assert not operation.call_args.args[4].exists()
    assert "chiliarch.tasks" in operation.call_args.kwargs["capabilities"]
    assert "chiliarch.task_workdir" not in operation.call_args.kwargs["capabilities"]
    state.write_bytes(b"existing credential")
    with pytest.raises(ValueError, match="state 已存在"):
        await pair(
            "http://example.invalid",
            "test-code",
            "Undefined",
            "test-machine",
            state,
            "介绍",
        )
    assert operation.await_count == 1 and state.read_bytes() == b"existing credential"


async def test_status_route_uses_runtime_auth_and_openapi(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from Undefined.api import webchat_store

    monkeypatch.setattr(
        webchat_store, "WEBCHAT_CONVERSATIONS_DIR", tmp_path / "webchat"
    )
    cfg = Config.from_mapping({"api": {"auth_key": "test-key"}}, strict=False)
    ctx = RuntimeAPIContext(
        config_getter=lambda: cfg,
        onebot=None,
        ai=None,
        command_dispatcher=None,
        queue_manager=None,
        history_manager=None,
        chiliarch_service=ChiliarchService(
            SimpleNamespace(), state_path=tmp_path / "unpaired.db"
        ),
    )
    server = RuntimeAPIServer(ctx, host="127.0.0.1", port=0)
    async with TestClient(TestServer(server._create_app())) as client:
        denied = await client.get("/api/v1/chiliarch/status")
        assert denied.status == 401
        response = await client.get(
            "/api/v1/chiliarch/status", headers={"X-Undefined-API-Key": "test-key"}
        )
        assert response.status == 200
        body = await response.json()
        assert body["state"] == "disabled" and "credential" not in json.dumps(body)
        schema = await (await client.get("/openapi.json")).json()
        assert "/api/v1/chiliarch/status" in schema["paths"]
