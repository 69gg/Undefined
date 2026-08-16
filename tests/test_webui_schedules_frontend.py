"""Frontend contracts for the automations list / canvas pages."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Final

from Undefined.utils import io as async_io

SCHEDULES_JS: Final[Path] = Path("src/Undefined/webui/static/js/schedules.js")


def _read_source(path: Path) -> str:
    text = asyncio.run(async_io.read_text(path))
    assert text is not None
    return text


def test_save_reloads_list_and_scrolls_to_list_page() -> None:
    source = _read_source(SCHEDULES_JS)
    save_fn = source.split("async function save()", 1)[1].split(
        "async function removeSelected()", 1
    )[0]
    refresh_fn = source.split("async function refresh(options = {})", 1)[1].split(
        "function maybeOpenFromQuery()", 1
    )[0]

    assert "if (scheduleState.busy && !force) return;" in refresh_fn
    assert "await refresh({ force: true, skipOpenFromQuery: true });" in save_fn
    assert 'showSchedulePage("list")' in save_fn
