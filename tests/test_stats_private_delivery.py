from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

import Undefined.services.command as command_module
from Undefined.services.command import CommandDispatcher
from Undefined.utils import io as async_io


def _summary() -> dict[str, Any]:
    return {
        "total_calls": 2,
        "total_tokens": 50,
        "prompt_tokens": 40,
        "completion_tokens": 10,
        "avg_duration": 1.5,
        "models": {
            "model-a": {
                "calls": 2,
                "tokens": 50,
                "prompt_tokens": 40,
                "completion_tokens": 10,
            }
        },
        "call_types": {"chat": 2},
        "daily_stats": {
            "2026-07-17": {
                "calls": 2,
                "tokens": 50,
                "prompt_tokens": 40,
                "completion_tokens": 10,
            }
        },
    }


async def _dispatcher(tmp_path: Path) -> tuple[CommandDispatcher, Path]:
    dispatcher = cast(Any, CommandDispatcher.__new__(CommandDispatcher))
    dispatcher.config = SimpleNamespace(bot_qq=10000)
    dispatcher.sender = SimpleNamespace(send_private_message=AsyncMock())
    dispatcher._token_usage_storage = SimpleNamespace(
        get_summary=AsyncMock(return_value=_summary())
    )
    render_dir = tmp_path / "stats-run"

    async def create_render_dir() -> Path:
        return await async_io.ensure_dir(render_dir)

    async def generate_charts(
        _summary_value: dict[str, Any],
        target: Path,
        _days: int,
    ) -> None:
        for name in ("line_chart", "bar_chart", "pie_chart", "table"):
            await async_io.write_bytes(target / f"stats_{name}.png", b"png")

    dispatcher._create_stats_render_dir = create_render_dir
    dispatcher._generate_stats_charts = generate_charts
    return dispatcher, render_dir


@pytest.mark.asyncio
async def test_private_stats_uses_one_forward_delivery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(command_module, "_MATPLOTLIB_AVAILABLE", True)
    dispatcher, render_dir = await _dispatcher(tmp_path)
    send_message = AsyncMock()
    send_forward = AsyncMock()

    await dispatcher._handle_stats_private(
        12345,
        12345,
        ["7d"],
        send_message=send_message,
        send_forward=send_forward,
    )

    send_message.assert_not_awaited()
    send_forward.assert_awaited_once()
    call = send_forward.await_args
    assert call is not None
    assert call.args[0] == 12345
    assert len(call.args[1]) == 6
    assert "总调用: 2" in call.kwargs["history_message"]
    assert not await async_io.exists(render_dir)


@pytest.mark.asyncio
async def test_private_stats_bundle_failure_keeps_text_summary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(command_module, "_MATPLOTLIB_AVAILABLE", True)
    dispatcher, render_dir = await _dispatcher(tmp_path)
    send_message = AsyncMock()
    send_forward = AsyncMock(side_effect=RuntimeError("upload failed"))

    await dispatcher._handle_stats_private(
        12345,
        12345,
        ["7d"],
        send_message=send_message,
        send_forward=send_forward,
    )

    send_message.assert_awaited_once()
    call = send_message.await_args
    assert call is not None
    message = str(call.args[0])
    assert "总调用次数: 2" in message
    assert "图表发送失败" in message
    assert not await async_io.exists(render_dir)
