from __future__ import annotations

import asyncio
import os
from pathlib import Path
import sys
from typing import cast

import pytest
from aiohttp import web

from Undefined.webui import core
from Undefined.webui.app import on_shutdown
from Undefined.webui.routes._shared import BOT_APP_KEY


@pytest.mark.asyncio
@pytest.mark.skipif(os.name == "nt", reason="POSIX SIGTERM child fixture")
@pytest.mark.parametrize("force_timeout", [None, 0.05])
@pytest.mark.parametrize("entrypoint", ["controller", "shutdown"])
async def test_stop_honors_graceful_completion_and_configured_deadline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    force_timeout: float | None,
    entrypoint: str,
) -> None:
    child = tmp_path / "child.py"
    child.write_text(
        "import asyncio, signal\n"
        "from pathlib import Path\n"
        "async def main() -> None:\n"
        "    root = Path(__file__).parent\n"
        "    stop = asyncio.Event()\n"
        "    asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, stop.set)\n"
        "    (root / 'ready').touch()\n"
        "    await stop.wait()\n"
        "    (root / 'started').touch()\n"
        "    await asyncio.sleep(6)\n"
        "    (root / 'finished').touch()\n"
        "asyncio.run(main())\n"
    )
    monkeypatch.setattr(core, "BOT_COMMAND", (sys.executable, str(child)))
    controller = core.BotProcessController(
        stop_timeout_getter=(lambda: force_timeout)
        if force_timeout is not None
        else None
    )
    await controller.start()
    process = controller._process
    assert process is not None

    async def ready() -> None:
        while not (tmp_path / "ready").exists():
            await asyncio.sleep(0.01)

    try:
        await asyncio.wait_for(ready(), 3)
        if entrypoint == "shutdown":
            await asyncio.wait_for(
                on_shutdown(cast(web.Application, {BOT_APP_KEY: controller})), 8
            )
            status = controller.status()
        else:
            status = await asyncio.wait_for(controller.stop(), 8)
        assert not status["running"]
        assert (tmp_path / "started").exists()
        assert (tmp_path / "finished").exists() is (force_timeout is None)
        assert (process.returncode == 0) is (force_timeout is None)
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()


@pytest.mark.asyncio
@pytest.mark.skipif(os.name == "nt", reason="POSIX SIGTERM child fixture")
async def test_repeated_stop_cancellation_waits_for_process_and_releases_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    child = tmp_path / "child.py"
    child.write_text(
        "import asyncio, signal\n"
        "from pathlib import Path\n"
        "async def main() -> None:\n"
        "    root = Path(__file__).parent\n"
        "    stop = asyncio.Event()\n"
        "    asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, stop.set)\n"
        "    (root / 'ready').touch()\n"
        "    await stop.wait()\n"
        "    (root / 'stopping').touch()\n"
        "    while not (root / 'release').exists():\n"
        "        await asyncio.sleep(0.01)\n"
        "    (root / 'finished').touch()\n"
        "asyncio.run(main())\n"
    )
    monkeypatch.setattr(core, "BOT_COMMAND", (sys.executable, str(child)))
    controller = core.BotProcessController()
    await controller.start()
    process = controller._process
    assert process is not None

    async def wait_for_file(name: str) -> None:
        while not (tmp_path / name).exists():
            await asyncio.sleep(0.01)

    stop_task: asyncio.Task[dict[str, object]] | None = None
    try:
        await asyncio.wait_for(wait_for_file("ready"), 3)
        stop_task = asyncio.create_task(controller.stop())
        await asyncio.wait_for(wait_for_file("stopping"), 3)
        for _ in range(2):
            stop_task.cancel()
            await asyncio.sleep(0)
        assert not stop_task.done()
        assert controller.status()["running"]
        assert controller._lock.locked()
        (tmp_path / "release").touch()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(stop_task, 3)
        assert (tmp_path / "finished").exists()
        assert process.returncode == 0
        assert not controller._lock.locked()
        assert controller._watch_task is None
        assert not (await asyncio.wait_for(controller.stop(), 1))["running"]
    finally:
        (tmp_path / "release").touch()
        if process.returncode is None:
            process.kill()
            await process.wait()
        if stop_task is not None:
            await asyncio.gather(stop_task, return_exceptions=True)
