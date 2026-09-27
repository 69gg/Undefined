from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from playwright.async_api import Error, Page, async_playwright

import Undefined.render as render_module


@pytest.fixture
async def content_page() -> AsyncIterator[Page]:
    async with async_playwright() as playwright:
        try:
            browser = await playwright.chromium.launch(headless=True)
        except Error as error:
            if render_module._is_missing_playwright_browser(error):
                pytest.skip("Run `uv run playwright install chromium` for layout tests")
            raise
        try:
            yield await browser.new_page(viewport={"width": 900, "height": 800})
        finally:
            await browser.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("css", "padding", "expected_width"),
    [
        ("body { width: 400px; }", 28, 456),
        ("html, body { width: 400px; }", 28, 456),
        ("html { width: 640px; } body { width: 400px; }", 28, 696),
        ("html { width: 100%; } body { width: 400px; }", 28, 900),
        ("body { max-width: 400px; }", 28, 456),
        ("body { width: 400px; } div { width: 600px; }", 28, 656),
        ("body { width: 100%; }", 28, 900),
        ("body { width: 100%; }", 0, 900),
        ("div { width: 400px; }", 0, 900),
        ("body { margin: 8px; }", 28, 900),
        ("body { margin: 8px; }", 0, 900),
    ],
)
async def test_fit_viewport_uses_page_layout(
    content_page: Page, css: str, padding: int, expected_width: int
) -> None:
    await content_page.set_content(
        "<!doctype html><style>html, body { margin: 0; }"
        f"{css}</style><body><div>content</div></body>"
    )

    fitted_width = await render_module._fit_viewport_to_content(
        content_page, 900, padding
    )

    assert fitted_width == expected_width
    assert content_page.viewport_size == {"width": expected_width, "height": 800}


@pytest.mark.asyncio
async def test_content_width_probe_handles_many_descendants(
    content_page: Page,
) -> None:
    await content_page.set_content(
        "<!doctype html><style>html, body { width: 400px; margin: 0; }</style>"
        "<body></body>"
    )
    # 150,000 项超过 Chromium 中 Math.max(...widths) 的实参数量上限。
    await content_page.evaluate(
        "() => { document.body.innerHTML = '<span></span>'.repeat(150000); }"
    )

    assert await content_page.evaluate(render_module._CONTENT_WIDTH_SCRIPT) == 400
