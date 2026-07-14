"""HTML 渲染模块：将 HTML/Markdown 渲染为图片"""

import asyncio
import logging
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, Literal, TypeVar

import markdown
from playwright.async_api import Browser, Page, Playwright, Route, async_playwright


from Undefined.config import get_config
from Undefined.utils.io import find_executable, is_file, resolve_path
from Undefined.utils.render_cache import compute_render_cache_key, get_render_cache

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
_render_active_count = 0

# 默认并发限制：Linux 默认 1，其它平台默认 2
_DEFAULT_MAX_CONCURRENT = 1 if sys.platform == "linux" else 2
_SYSTEM_CHROMIUM_COMMANDS = (
    "google-chrome-stable",
    "google-chrome",
    "chromium",
    "chromium-browser",
    "microsoft-edge-stable",
)
_RenderResult = TypeVar("_RenderResult")


def _safe_file_size(path: Path) -> int:
    """同步取文件大小（在 ``asyncio.to_thread`` 中调用）；不存在/不可读时返回 0。"""
    try:
        return path.stat().st_size
    except OSError:
        return 0


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


async def _resolve_configured_browser_executable() -> str | None:
    """读取显式配置的浏览器路径；配置错误时不静默回退。"""
    try:
        runtime_config = get_config(strict=False)
    except Exception:
        logger.debug("[渲染] 读取浏览器路径配置失败", exc_info=True)
        return None

    configured = str(
        getattr(runtime_config, "render_browser_executable_path", "") or ""
    ).strip()
    if not configured:
        return None

    path = await resolve_path(configured)
    if not await is_file(path):
        raise FileNotFoundError(f"配置的渲染浏览器不存在: {path}")
    return str(path)


async def _find_system_browser_executable() -> str | None:
    """在 Playwright 自带 Chromium 缺失时查找已安装的系统浏览器。"""
    for command in _SYSTEM_CHROMIUM_COMMANDS:
        executable = await find_executable(command)
        if executable:
            return executable
    return None


def _is_missing_playwright_browser(error: BaseException) -> bool:
    text = str(error)
    return "Executable doesn't exist" in text or "playwright install" in text


async def _get_browser() -> Browser:
    """获取或创建浏览器实例（懒加载单例）"""
    global _playwright, _browser

    if _browser is not None:
        return _browser

    async with _browser_lock:
        if _browser is not None:
            return _browser

        configured_executable = await _resolve_configured_browser_executable()
        playwright = await async_playwright().start()
        try:
            if configured_executable is not None:
                browser = await playwright.chromium.launch(
                    headless=True,
                    executable_path=configured_executable,
                )
            else:
                try:
                    browser = await playwright.chromium.launch(headless=True)
                except Exception as exc:
                    system_executable = await _find_system_browser_executable()
                    if (
                        not _is_missing_playwright_browser(exc)
                        or system_executable is None
                    ):
                        raise
                    logger.warning(
                        "[render] Playwright Chromium 未安装，回退到系统浏览器: %s",
                        system_executable,
                    )
                    browser = await playwright.chromium.launch(
                        headless=True,
                        executable_path=system_executable,
                    )
        except Exception:
            await playwright.stop()
            raise
        _playwright = playwright
        _browser = browser
        logger.info("[渲染] 浏览器实例已启动")
        return _browser


async def _get_semaphore() -> asyncio.Semaphore:
    """获取渲染并发信号量"""
    global _render_semaphore, _render_semaphore_limit

    configured_limit = _resolve_render_browser_max_concurrency()
    if _render_semaphore is None:
        _render_semaphore = asyncio.Semaphore(configured_limit)
        _render_semaphore_limit = configured_limit
    elif _render_semaphore_limit != configured_limit:
        if _render_active_count <= 0:
            _render_semaphore = asyncio.Semaphore(configured_limit)
            _render_semaphore_limit = configured_limit
    return _render_semaphore


async def close_browser() -> None:
    """关闭浏览器实例，应在程序退出时调用"""
    global _playwright, _browser, _render_semaphore, _render_semaphore_limit
    global _render_active_count

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
        _render_active_count = 0


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
    screenshot_scale: Literal["css", "device"] = "device",
    screenshot_style: str | None = None,
    timeout_ms: int = 60000,
    proxy: str | None = None,
) -> None:
    """
    将 HTML 字符串转换为 PNG 图片

    参数:
        html_content: 完整的 HTML 字符串
        output_path: 输出图片路径 (例如 'result.png')
        viewport_width: 视口宽度（像素），默认 1280
        screenshot_selector: 仅截图匹配的元素，默认截整页
        screenshot_scale: 输出像素尺度，device 按 DPR 输出，css 按 CSS 像素输出
        screenshot_style: 仅在截图期间注入的 CSS 样式
        timeout_ms: 截图超时时间（毫秒），默认 60000
        proxy: 保留用于调用兼容和缓存隔离；离线上下文不会发出网络请求
    """
    cache = await get_render_cache()
    cache_key = compute_render_cache_key(
        html_content,
        viewport_width,
        screenshot_selector,
        proxy,
        screenshot_scale,
        screenshot_style,
    )

    if await cache.copy_to(cache_key, output_path):
        return

    async def _capture(page: Page) -> None:
        await page.wait_for_load_state("networkidle", timeout=timeout_ms)
        await asyncio.sleep(1)
        if screenshot_selector:
            await page.locator(screenshot_selector).first.screenshot(
                path=output_path,
                scale=screenshot_scale,
                style=screenshot_style,
                timeout=timeout_ms,
            )
        else:
            await page.screenshot(
                path=output_path,
                full_page=True,
                scale=screenshot_scale,
                style=screenshot_style,
                timeout=timeout_ms,
            )

    await render_html_with_page(
        html_content,
        _capture,
        viewport_width=viewport_width,
        timeout_ms=timeout_ms,
        proxy=proxy,
    )

    output_size = await asyncio.to_thread(_safe_file_size, Path(output_path))
    if output_size > 0:
        await cache.put(cache_key, output_path, output_size)


async def render_html_with_page(
    html_content: str,
    callback: Callable[[Page], Awaitable[_RenderResult]],
    *,
    viewport_width: int = 1280,
    timeout_ms: int = 60000,
    proxy: str | None = None,
) -> _RenderResult:
    """在共享浏览器实例中打开 HTML 页面并交给调用方渲染。

    ``proxy`` 在移出 ``context_kwargs`` 后仍刻意保留，以兼容现有调用；上层
    ``render_html_to_image`` 继续用它隔离缓存键，离线浏览器上下文不会使用它。
    """
    browser = await _get_browser()
    semaphore = await _get_semaphore()

    global _render_active_count

    async with semaphore:
        _render_active_count += 1
        context = None
        try:
            context_kwargs: dict[str, Any] = {
                "device_scale_factor": 2,
                "offline": True,
                "service_workers": "block",
                "viewport": {"width": viewport_width, "height": 800},
            }
            context = await browser.new_context(**context_kwargs)
            await context.route("**/*", _abort_render_network_request)
            page = await context.new_page()
            page.set_default_timeout(timeout_ms)
            await page.set_content(html_content)
            return await callback(page)
        finally:
            try:
                if context is not None:
                    await context.close()
            finally:
                _render_active_count = max(0, _render_active_count - 1)


async def _abort_render_network_request(route: Route) -> None:
    """终止渲染上下文中的所有网络请求，避免 DNS 重绑定绕过。"""
    await route.abort()
