from __future__ import annotations

import base64
from html import escape

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request
from playwright.async_api import Error, Route, async_playwright

from test_webui_runtime_chat_behavior import run_scenario
from Undefined.render import _is_missing_playwright_browser
from Undefined.webui.app import security_headers_middleware


@pytest.mark.parametrize("scheme", ["http", "https"])
async def test_rendered_remote_image_loads_under_actual_webui_csp(scheme: str) -> None:
    rendered = run_scenario("markdown_sanitizes_unsafe_content")
    source = next(
        image["src"]
        for image in rendered["images"]
        if image["src"].startswith("https:")
    )
    image_url = source.replace("https:", f"{scheme}:", 1)
    page_url = "http://management.example.test/index"
    script_url = "https://script.example.test/blocked.js"
    fetch_url = "https://api.example.test/blocked"
    html = (
        f'<img id="remote" src="{escape(image_url, quote=True)}">'
        f'<script src="{script_url}"></script>'
    )

    async def handler(request: web.Request) -> web.StreamResponse:
        return web.Response(text=html, content_type="text/html")

    response = await security_headers_middleware(
        make_mocked_request("GET", "/"), handler
    )
    csp = response.headers["Content-Security-Policy"]
    intercepted: list[str] = []
    pixel = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jZrQAAAAASUVORK5CYII="
    )

    async def fulfill(route: Route) -> None:
        intercepted.append(route.request.url)
        if route.request.url == page_url:
            await route.fulfill(
                status=200,
                content_type="text/html",
                headers={"Content-Security-Policy": csp},
                body=html,
            )
        else:
            await route.fulfill(status=200, content_type="image/png", body=pixel)

    async with async_playwright() as playwright:
        try:
            browser = await playwright.chromium.launch(headless=True)
        except Error as error:
            if _is_missing_playwright_browser(error):
                pytest.skip(
                    "Run `uv run playwright install chromium` for CSP browser tests"
                )
            raise
        try:
            page = await browser.new_page()
            await page.route("**/*", fulfill)
            await page.goto(page_url, wait_until="load")
            assert await page.locator("#remote").evaluate(
                "image => image.complete && image.naturalWidth === 1"
            )
            assert await page.evaluate(
                "url => fetch(url).then(() => false).catch(() => true)", fetch_url
            )
            assert image_url in intercepted
            assert script_url not in intercepted
            assert fetch_url not in intercepted
        finally:
            await browser.close()
