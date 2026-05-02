"""HTML 渲染模块：将 HTML/Markdown 渲染为图片"""

import asyncio
import logging
import markdown
import sys
from collections.abc import Awaitable, Callable
from playwright.async_api import async_playwright, Browser, Page, Playwright

from typing import Any, TypeVar

from Undefined.config import get_config

logger = logging.getLogger(__name__)

# --- Markdown 配置 ---
_MARKDOWN_EXTENSIONS = [
    "toc",
    "tables",
    "fenced_code",
    "codehilite",
    "md_in_html",
    "attr_list",
    "pymdownx.superfences",
    "pymdownx.arithmatex",
    "pymdownx.tasklist",
    "pymdownx.tilde",
    "pymdownx.emoji",
]

_MARKDOWN_EXTENSION_CONFIGS: dict[str, dict[str, Any]] = {
    "pymdownx.superfences": {
        "custom_fences": [
            {
                "name": "mermaid",
                "class": "mermaid",
                "format": lambda source, language, css_class, options, md, **kwargs: (
                    f'<pre class="{css_class}">{source}</pre>'
                ),
            }
        ]
    },
    "pymdownx.arithmatex": {
        "generic": True,
    },
}


# --- 浏览器实例管理（懒加载单例） ---
_playwright: Playwright | None = None
_browser: Browser | None = None
_browser_lock = asyncio.Lock()
_render_semaphore: asyncio.Semaphore | None = None
_render_semaphore_limit: int | None = None

# 默认并发限制：Linux 默认 1，其它平台默认 2
_DEFAULT_MAX_CONCURRENT = 1 if sys.platform == "linux" else 2
_RenderResult = TypeVar("_RenderResult")


def _resolve_render_browser_max_concurrency() -> int:
    """解析渲染浏览器并发上限，0 表示沿用平台默认值。"""
    try:
        runtime_config = get_config(strict=False)
    except Exception:
        logger.debug("[渲染] 读取配置失败，回退到默认浏览器并发上限", exc_info=True)
        return _DEFAULT_MAX_CONCURRENT

    raw_limit = getattr(runtime_config, "render_browser_max_concurrency", 0)
    try:
        configured_limit = int(raw_limit)
    except (TypeError, ValueError):
        configured_limit = 0

    if configured_limit <= 0:
        return _DEFAULT_MAX_CONCURRENT
    return configured_limit


async def _get_browser() -> Browser:
    """获取或创建浏览器实例（懒加载单例）"""
    global _playwright, _browser

    if _browser is not None:
        return _browser

    async with _browser_lock:
        if _browser is not None:
            return _browser

        _playwright = await async_playwright().start()
        _browser = await _playwright.chromium.launch(headless=True)
        logger.info("[渲染] 浏览器实例已启动")
        return _browser


async def _get_semaphore() -> asyncio.Semaphore:
    """获取渲染并发信号量"""
    global _render_semaphore, _render_semaphore_limit

    if _render_semaphore is None:
        configured_limit = _resolve_render_browser_max_concurrency()
        _render_semaphore = asyncio.Semaphore(configured_limit)
        _render_semaphore_limit = configured_limit
    return _render_semaphore


async def close_browser() -> None:
    """关闭浏览器实例，应在程序退出时调用"""
    global _playwright, _browser, _render_semaphore, _render_semaphore_limit

    async with _browser_lock:
        if _browser is not None:
            await _browser.close()
            _browser = None
            logger.info("[渲染] 浏览器实例已关闭")

        if _playwright is not None:
            await _playwright.stop()
            _playwright = None

        _render_semaphore = None
        _render_semaphore_limit = None


async def render_markdown_to_html(md_text: str) -> str:
    """将 Markdown 转换为带样式的 HTML 文本"""

    def _parse() -> str:
        return str(
            markdown.markdown(
                md_text,
                extensions=_MARKDOWN_EXTENSIONS,
                extension_configs=_MARKDOWN_EXTENSION_CONFIGS,
            )
        )

    # 使用 to_thread 在独立的线程中运行同步的 markdown 解析，避免阻塞主循环
    html_content = await asyncio.to_thread(_parse)

    # 拼接 HTML 模板（这部分是纯字符串操作，速度极快，无需放进线程）
    full_html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/github-markdown-css/5.2.0/github-markdown.min.css">
        <style>
            body {{ background-color: white; padding: 45px; }}
            .markdown-body {{ box-sizing: border-box; min-width: 200px; max-width: 980px; margin: 0 auto; }}
            .mermaid {{ background: transparent !important; border: none !important; }}
        </style>
        <script id="MathJax-script" async src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-chtml.js"></script>
        <script>
        window.MathJax = {{
          tex: {{ inlineMath: [['$', '$'], ['\\\\(', '\\\\)']] }}
        }};
        </script>
        <script src="https://cdn.jsdelivr.net/npm/mermaid@11.1.0/dist/mermaid.min.js"></script>
    </head>
    <body>
        <article class="markdown-body">
            {html_content}
        </article>
        <script>
            mermaid.initialize({{
                startOnLoad: true,
                theme: 'default',
                securityLevel: 'loose',
                fontFamily: 'arial'
            }});
        </script>
    </body>
    </html>
    """
    return full_html


async def render_html_to_image(
    html_content: str,
    output_path: str,
    *,
    viewport_width: int = 1280,
    screenshot_selector: str | None = None,
    timeout_ms: int = 60000,
) -> None:
    """
    将 HTML 字符串转换为 PNG 图片

    参数:
        html_content: 完整的 HTML 字符串
        output_path: 输出图片路径 (例如 'result.png')
        viewport_width: 视口宽度（像素），默认 1280
        screenshot_selector: 仅截图匹配的元素，默认截整页
        timeout_ms: 截图超时时间（毫秒），默认 60000
    """

    async def _capture(page: Page) -> None:
        # 等待网络空闲（确保 CDN 上的 MathJax/Mermaid 脚本加载完）
        await page.wait_for_load_state("networkidle", timeout=timeout_ms)

        # 给 Mermaid 一点时间执行 JS 绘图
        await asyncio.sleep(1)

        # 截图（带超时保护）
        if screenshot_selector:
            await page.locator(screenshot_selector).first.screenshot(
                path=output_path,
                timeout=timeout_ms,
            )
        else:
            await page.screenshot(
                path=output_path,
                full_page=True,
                timeout=timeout_ms,
            )

    await render_html_with_page(
        html_content,
        _capture,
        viewport_width=viewport_width,
        timeout_ms=timeout_ms,
    )


async def render_html_with_page(
    html_content: str,
    callback: Callable[[Page], Awaitable[_RenderResult]],
    *,
    viewport_width: int = 1280,
    timeout_ms: int = 60000,
    proxy: str | None = None,
) -> _RenderResult:
    """在共享浏览器实例中打开 HTML 页面并交给调用方渲染。"""
    browser = await _get_browser()
    semaphore = await _get_semaphore()

    async with semaphore:
        context_kwargs: dict[str, Any] = {
            "device_scale_factor": 2,
            "viewport": {"width": viewport_width, "height": 800},
        }
        if proxy:
            context_kwargs["proxy"] = {"server": proxy}
        context = await browser.new_context(**context_kwargs)
        page = await context.new_page()
        page.set_default_timeout(timeout_ms)

        try:
            await page.set_content(html_content)
            return await callback(page)
        finally:
            await context.close()
