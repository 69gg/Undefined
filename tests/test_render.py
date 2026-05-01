from __future__ import annotations

from collections.abc import Iterator
from types import SimpleNamespace

import pytest

import Undefined.render as render_module


def _reset_render_state() -> None:
    render_module._playwright = None
    render_module._browser = None
    render_module._render_semaphore = None
    render_module._render_semaphore_limit = None


@pytest.fixture(autouse=True)
def _reset_render_module_state() -> Iterator[None]:
    _reset_render_state()
    yield
    _reset_render_state()


@pytest.mark.asyncio
async def test_get_semaphore_uses_platform_default_when_auto(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime_config = SimpleNamespace(render_browser_max_concurrency=0)
    monkeypatch.setattr(
        render_module,
        "get_config",
        lambda strict=False: runtime_config,
    )

    semaphore = await render_module._get_semaphore()

    assert (
        render_module._render_semaphore_limit == render_module._DEFAULT_MAX_CONCURRENT
    )
    assert semaphore._value == render_module._DEFAULT_MAX_CONCURRENT


@pytest.mark.asyncio
async def test_get_semaphore_uses_configured_browser_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime_config = SimpleNamespace(render_browser_max_concurrency=3)
    monkeypatch.setattr(
        render_module,
        "get_config",
        lambda strict=False: runtime_config,
    )

    semaphore = await render_module._get_semaphore()

    assert render_module._render_semaphore_limit == 3
    assert semaphore._value == 3


@pytest.mark.asyncio
async def test_get_semaphore_keeps_existing_instance_when_limit_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime_config = SimpleNamespace(render_browser_max_concurrency=2)
    monkeypatch.setattr(
        render_module,
        "get_config",
        lambda strict=False: runtime_config,
    )

    first = await render_module._get_semaphore()
    runtime_config.render_browser_max_concurrency = 4
    second = await render_module._get_semaphore()

    assert first is second
    assert render_module._render_semaphore_limit == 2
    assert second._value == 2
