from __future__ import annotations

import asyncio
import logging
import os
import signal
import pytest

from Undefined.main import _run_until_shutdown, install_shutdown_signal_handlers

logger = logging.getLogger("test-main-shutdown")


class _SlowOneBot:
    def __init__(self) -> None:
        self.cancelled = False

    async def run_with_reconnect(self) -> None:
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            self.cancelled = True
            raise


class _FailingOneBot:
    async def run_with_reconnect(self) -> None:
        raise RuntimeError("connection boom")


@pytest.mark.asyncio
async def test_run_until_shutdown_cancels_onebot_on_signal() -> None:
    onebot = _SlowOneBot()
    shutdown_event = asyncio.Event()

    task = asyncio.create_task(
        _run_until_shutdown(onebot, shutdown_event, logger)  # type: ignore[arg-type]
    )
    await asyncio.sleep(0.05)
    shutdown_event.set()
    await asyncio.wait_for(task, timeout=2)

    assert onebot.cancelled is True


@pytest.mark.asyncio
async def test_run_until_shutdown_propagates_connection_error() -> None:
    with pytest.raises(RuntimeError, match="connection boom"):
        await _run_until_shutdown(
            _FailingOneBot(),  # type: ignore[arg-type]
            asyncio.Event(),
            logger,
        )


@pytest.mark.asyncio
async def test_install_shutdown_signal_handlers_reacts_to_sigterm() -> None:
    if not hasattr(signal, "SIGTERM"):  # pragma: no cover - 非 POSIX 平台
        pytest.skip("SIGTERM unavailable")

    original = signal.getsignal(signal.SIGTERM)
    guard = install_shutdown_signal_handlers(logger)
    if signal.getsignal(signal.SIGTERM) is signal.SIG_DFL:
        pytest.skip("当前事件循环不支持信号处理器")
    try:
        os.kill(os.getpid(), signal.SIGTERM)
        await asyncio.wait_for(guard.event.wait(), timeout=2)
        assert guard.event.is_set()
    finally:
        guard.restore()
    assert signal.getsignal(signal.SIGTERM) is original


@pytest.mark.asyncio
async def test_install_shutdown_signal_handlers_restore_returns_previous_handler() -> (
    None
):
    if not hasattr(signal, "SIGTERM"):  # pragma: no cover - 非 POSIX 平台
        pytest.skip("SIGTERM unavailable")

    def _previous_handler(signum: object, frame: object) -> None:  # pragma: no cover
        return None

    original = signal.signal(signal.SIGTERM, _previous_handler)
    try:
        guard = install_shutdown_signal_handlers(logger)
        guard.restore()
        assert signal.getsignal(signal.SIGTERM) is _previous_handler
    finally:
        signal.signal(signal.SIGTERM, original)


@pytest.mark.asyncio
async def test_install_shutdown_signal_handlers_restore_is_idempotent() -> None:
    if not hasattr(signal, "SIGTERM"):  # pragma: no cover - 非 POSIX 平台
        pytest.skip("SIGTERM unavailable")

    original = signal.getsignal(signal.SIGTERM)
    guard = install_shutdown_signal_handlers(logger)
    guard.restore()
    # 二次调用为空操作：previous 已清空，不得抛错或再改信号状态
    guard.restore()
    assert signal.getsignal(signal.SIGTERM) is original


@pytest.mark.asyncio
async def test_install_shutdown_signal_handlers_returns_fresh_event() -> None:
    guard = install_shutdown_signal_handlers(logger)
    assert isinstance(guard.event, asyncio.Event)
    assert guard.event.is_set() is False
    guard.restore()
