from __future__ import annotations

import asyncio
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

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


@pytest.mark.asyncio
async def test_render_html_with_page_closes_context_when_new_page_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FailingContext:
        def __init__(self) -> None:
            self.closed = False

        async def new_page(self) -> Any:
            raise RuntimeError("new page failed")

        async def close(self) -> None:
            self.closed = True

    class _FakeBrowser:
        def __init__(self, context: _FailingContext) -> None:
            self.context = context

        async def new_context(self, **_kwargs: Any) -> _FailingContext:
            return self.context

    context = _FailingContext()

    async def _fake_get_browser() -> _FakeBrowser:
        return _FakeBrowser(context)

    async def _fake_get_semaphore() -> asyncio.Semaphore:
        return asyncio.Semaphore(1)

    async def _unused_callback(_page: Any) -> None:
        raise AssertionError("callback should not run")

    monkeypatch.setattr(render_module, "_get_browser", _fake_get_browser)
    monkeypatch.setattr(render_module, "_get_semaphore", _fake_get_semaphore)

    with pytest.raises(RuntimeError, match="new page failed"):
        await render_module.render_html_with_page("<html></html>", _unused_callback)

    assert context.closed is True
