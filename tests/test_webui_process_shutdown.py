from __future__ import annotations

import asyncio
import os
from pathlib import Path
import sys

import pytest

from Undefined.webui import core


@pytest.mark.asyncio
@pytest.mark.skipif(os.name == "nt", reason="POSIX SIGTERM child fixture")
@pytest.mark.parametrize("force_timeout", [None, 0.05])
async def test_stop_honors_graceful_completion_and_configured_deadline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    force_timeout: float | None,
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
        status = await asyncio.wait_for(controller.stop(), 8)
        assert not status["running"]
        assert (tmp_path / "started").exists()
        assert (tmp_path / "finished").exists() is (force_timeout is None)
        assert (process.returncode == 0) is (force_timeout is None)
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()
