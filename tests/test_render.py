from __future__ import annotations

import asyncio
import shutil
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import Undefined.render as render_module
from Undefined.utils.io import write_bytes


def _reset_render_state() -> None:
    render_module._playwright = None
    render_module._browser = None
    render_module._render_semaphore = None
    render_module._render_semaphore_limit = None
    render_module._render_active_count = 0


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
async def test_get_semaphore_recreates_idle_instance_when_limit_changes(
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

    assert first is not second
    assert render_module._render_semaphore_limit == 4
    assert second._value == 4


@pytest.mark.asyncio
async def test_get_semaphore_waits_for_active_instance_before_recreating(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime_config = SimpleNamespace(render_browser_max_concurrency=2)
    monkeypatch.setattr(
        render_module,
        "get_config",
        lambda strict=False: runtime_config,
    )

    first = await render_module._get_semaphore()
    render_module._render_active_count = 1
    runtime_config.render_browser_max_concurrency = 4
    active = await render_module._get_semaphore()
    render_module._render_active_count = 0
    recreated = await render_module._get_semaphore()

    assert active is first
    assert recreated is not first
    assert render_module._render_semaphore_limit == 4
    assert recreated._value == 4


@pytest.mark.asyncio
async def test_get_browser_stops_playwright_when_launch_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeChromium:
        async def launch(self, *, headless: bool) -> Any:
            assert headless is True
            raise RuntimeError("launch failed")

    class _FakePlaywright:
        def __init__(self) -> None:
            self.chromium = _FakeChromium()
            self.stopped = False

        async def stop(self) -> None:
            self.stopped = True

    class _FakePlaywrightFactory:
        def __init__(self, playwright: _FakePlaywright) -> None:
            self.playwright = playwright

        async def start(self) -> _FakePlaywright:
            return self.playwright

    playwright = _FakePlaywright()
    monkeypatch.setattr(
        render_module,
        "async_playwright",
        lambda: _FakePlaywrightFactory(playwright),
    )

    with pytest.raises(RuntimeError, match="launch failed"):
        await render_module._get_browser()

    assert playwright.stopped is True
    assert render_module._playwright is None
    assert render_module._browser is None


@pytest.mark.asyncio
async def test_get_browser_falls_back_to_installed_system_chrome(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    browser = object()

    class _FakeChromium:
        def __init__(self) -> None:
            self.executable_paths: list[str | None] = []

        async def launch(
            self,
            *,
            headless: bool,
            executable_path: str | None = None,
        ) -> Any:
            assert headless is True
            self.executable_paths.append(executable_path)
            if executable_path is None:
                raise RuntimeError(
                    "BrowserType.launch: Executable doesn't exist; playwright install"
                )
            return browser

    class _FakePlaywright:
        def __init__(self) -> None:
            self.chromium = _FakeChromium()
            self.stopped = False

        async def stop(self) -> None:
            self.stopped = True

    class _FakePlaywrightFactory:
        def __init__(self, playwright: _FakePlaywright) -> None:
            self.playwright = playwright

        async def start(self) -> _FakePlaywright:
            return self.playwright

    playwright = _FakePlaywright()
    monkeypatch.setattr(
        render_module,
        "get_config",
        lambda strict=False: SimpleNamespace(render_browser_executable_path=""),
    )
    monkeypatch.setattr(
        render_module,
        "async_playwright",
        lambda: _FakePlaywrightFactory(playwright),
    )
    monkeypatch.setattr(
        shutil,
        "which",
        lambda command: (
            "/usr/bin/google-chrome-stable"
            if command == "google-chrome-stable"
            else None
        ),
    )

    result = await render_module._get_browser()

    assert result is browser
    assert playwright.chromium.executable_paths == [
        None,
        "/usr/bin/google-chrome-stable",
    ]
    assert playwright.stopped is False


@pytest.mark.asyncio
async def test_get_browser_uses_configured_executable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    executable = tmp_path / "chrome"
    await write_bytes(executable, b"binary")
    browser = object()

    class _FakeChromium:
        async def launch(
            self,
            *,
            headless: bool,
            executable_path: str,
        ) -> Any:
            assert headless is True
            assert executable_path == str(executable)
            return browser

    class _FakePlaywright:
        def __init__(self) -> None:
            self.chromium = _FakeChromium()

        async def stop(self) -> None:
            return None

    class _FakePlaywrightFactory:
        async def start(self) -> _FakePlaywright:
            return _FakePlaywright()

    monkeypatch.setattr(
        render_module,
        "get_config",
        lambda strict=False: SimpleNamespace(
            render_browser_executable_path=str(executable)
        ),
    )
    monkeypatch.setattr(
        render_module,
        "async_playwright",
        lambda: _FakePlaywrightFactory(),
    )

    result = await render_module._get_browser()

    assert result is browser


@pytest.mark.asyncio
async def test_render_html_with_page_closes_context_when_new_page_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FailingContext:
        def __init__(self) -> None:
            self.closed = False

        async def route(self, pattern: str, _handler: Any) -> None:
            assert pattern == "**/*"

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
    assert render_module._render_active_count == 0


@pytest.mark.asyncio
async def test_render_html_with_page_decrements_active_count_when_new_context_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeBrowser:
        async def new_context(self, **_kwargs: Any) -> Any:
            raise RuntimeError("new context failed")

    async def _fake_get_browser() -> _FakeBrowser:
        return _FakeBrowser()

    async def _fake_get_semaphore() -> asyncio.Semaphore:
        return asyncio.Semaphore(1)

    async def _unused_callback(_page: Any) -> None:
        raise AssertionError("callback should not run")

    monkeypatch.setattr(render_module, "_get_browser", _fake_get_browser)
    monkeypatch.setattr(render_module, "_get_semaphore", _fake_get_semaphore)

    with pytest.raises(RuntimeError, match="new context failed"):
        await render_module.render_html_with_page("<html></html>", _unused_callback)

    assert render_module._render_active_count == 0


@pytest.mark.asyncio
async def test_render_html_with_page_active_count_stays_non_negative_after_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakePage:
        def set_default_timeout(self, _timeout_ms: int) -> None:
            pass

        async def set_content(self, _html_content: str) -> None:
            pass

    class _FakeContext:
        async def route(self, pattern: str, _handler: Any) -> None:
            assert pattern == "**/*"

        async def new_page(self) -> _FakePage:
            return _FakePage()

        async def close(self) -> None:
            pass

    class _FakeBrowser:
        async def new_context(self, **_kwargs: Any) -> _FakeContext:
            return _FakeContext()

    async def _fake_get_browser() -> _FakeBrowser:
        return _FakeBrowser()

    async def _fake_get_semaphore() -> asyncio.Semaphore:
        return asyncio.Semaphore(1)

    async def _callback(_page: Any) -> str:
        assert render_module._render_active_count == 1
        await render_module.close_browser()
        return "ok"

    monkeypatch.setattr(render_module, "_get_browser", _fake_get_browser)
    monkeypatch.setattr(render_module, "_get_semaphore", _fake_get_semaphore)

    result = await render_module.render_html_with_page("<html></html>", _callback)

    assert result == "ok"
    assert render_module._render_active_count == 0


@pytest.mark.asyncio
async def test_render_html_to_image_passes_long_screenshot_options(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    screenshot_kwargs: dict[str, Any] = {}
    render_page_kwargs: dict[str, Any] = {}

    class _FakeCache:
        async def copy_to(self, _key: str, _dest: str) -> bool:
            return False

        async def put(self, _key: str, _path: str, _size: int) -> None:
            raise AssertionError("empty fake output should not be cached")

    class _FakePage:
        async def wait_for_load_state(self, _state: str, *, timeout: int) -> None:
            assert timeout == 1234

        async def screenshot(self, **kwargs: Any) -> None:
            screenshot_kwargs.update(kwargs)

    async def _fake_get_render_cache() -> _FakeCache:
        return _FakeCache()

    async def _fake_render_html_with_page(
        html_content: str,
        callback: Any,
        **kwargs: Any,
    ) -> None:
        assert html_content == "<html><script>window.ready = true</script></html>"
        render_page_kwargs.update(kwargs)
        await callback(_FakePage())

    async def _no_sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr(render_module, "get_render_cache", _fake_get_render_cache)
    monkeypatch.setattr(
        render_module, "render_html_with_page", _fake_render_html_with_page
    )
    monkeypatch.setattr(asyncio, "sleep", _no_sleep)

    style = "html, body { margin: 0 !important; }"
    await render_module.render_html_to_image(
        "<html><script>window.ready = true</script></html>",
        str(tmp_path / "long.png"),
        viewport_width=900,
        screenshot_scale="css",
        screenshot_style=style,
        timeout_ms=1234,
    )

    assert render_page_kwargs["viewport_width"] == 900
    assert screenshot_kwargs == {
        "path": str(tmp_path / "long.png"),
        "full_page": True,
        "scale": "css",
        "style": style,
        "timeout": 1234,
    }


@pytest.mark.asyncio
async def test_render_html_with_page_blocks_private_network_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context_kwargs: dict[str, Any] = {}
    html_seen = ""
    route_pattern = ""
    route_handler: Any = None

    class _FakeRequest:
        def __init__(self, url: str) -> None:
            self.url = url

    class _FakeRoute:
        def __init__(self, url: str) -> None:
            self.request = _FakeRequest(url)
            self.aborted = False
            self.continued = False

        async def abort(self) -> None:
            self.aborted = True

        async def continue_(self) -> None:
            self.continued = True

    class _FakePage:
        def set_default_timeout(self, _timeout_ms: int) -> None:
            return None

        async def set_content(self, html_content: str) -> None:
            nonlocal html_seen
            html_seen = html_content

    class _FakeContext:
        async def route(self, pattern: str, handler: Any) -> None:
            nonlocal route_handler, route_pattern
            route_pattern = pattern
            route_handler = handler

        async def new_page(self) -> _FakePage:
            return _FakePage()

        async def close(self) -> None:
            return None

    class _FakeBrowser:
        async def new_context(self, **kwargs: Any) -> _FakeContext:
            context_kwargs.update(kwargs)
            return _FakeContext()

    async def _fake_get_browser() -> _FakeBrowser:
        return _FakeBrowser()

    async def _fake_get_semaphore() -> asyncio.Semaphore:
        return asyncio.Semaphore(1)

    async def _callback(_page: Any) -> None:
        assert route_handler is not None
        private_routes = [
            _FakeRoute("http://127.0.0.1:8080/private"),
            _FakeRoute("http://192.168.1.10/private"),
            _FakeRoute("http://metadata.google.internal/computeMetadata/v1/"),
            _FakeRoute("file:///etc/passwd"),
        ]
        public_route = _FakeRoute("https://example.com/app.js")

        for route in private_routes:
            await route_handler(route)
            assert route.aborted is True
            assert route.continued is False

        await route_handler(public_route)
        assert public_route.aborted is False
        assert public_route.continued is True

    monkeypatch.setattr(render_module, "_get_browser", _fake_get_browser)
    monkeypatch.setattr(render_module, "_get_semaphore", _fake_get_semaphore)

    html = '<html><script src="https://example.com/app.js"></script></html>'
    await render_module.render_html_with_page(html, _callback)

    assert html_seen == html
    assert route_pattern == "**/*"
    assert context_kwargs["service_workers"] == "block"
