import logging
from typing import Any, Dict

from Undefined.ai.crawl4ai_support import get_crawl4ai_capabilities
from Undefined.config import get_config

logger = logging.getLogger(__name__)


def _resolve_runtime_config(context: Dict[str, Any]) -> Any:
    runtime_config = context.get("runtime_config")
    if runtime_config is not None:
        return runtime_config
    return get_config(strict=False)


def _resolve_playwright_install_hint(error: BaseException) -> str | None:
    text = str(error)
    if (
        "Executable doesn't exist" in text
        or "playwright install" in text
        or "Looks like Playwright was just installed or updated" in text
    ):
        return (
            "网页获取依赖的 Playwright 浏览器未安装，"
            "请运行 `uv run playwright install` 后重试。"
        )
    return None


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    """对指定网页进行抓取、渲染并提取其中的文本或特定元素内容"""
    url = args.get("url", "")
    if not url:
        return "URL 不能为空"

    capabilities = get_crawl4ai_capabilities()
    if (
        not capabilities.available
        or capabilities.async_web_crawler is None
        or capabilities.browser_config is None
        or capabilities.crawler_run_config is None
    ):
        return "网页获取功能未启用（crawl4ai 未安装）"

    AsyncWebCrawler = capabilities.async_web_crawler
    BrowserConfig = capabilities.browser_config
    CrawlerRunConfig = capabilities.crawler_run_config
    ProxyConfig = capabilities.proxy_config

    max_chars = args.get("max_chars", 4096)

    try:
        runtime_config = _resolve_runtime_config(context)
        use_proxy = runtime_config.use_proxy
        proxy = runtime_config.http_proxy or runtime_config.https_proxy

        browser_config = BrowserConfig(
            headless=True,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            viewport_width=1280,
            viewport_height=720,
        )

        run_config_kwargs = {
            "word_count_threshold": 1,
            "cache_mode": "bypass",
            "page_timeout": 30000,
            "wait_for": "body",
            "delay_before_return_html": 2.0,
        }

        if use_proxy and proxy:
            logger.info(f"使用代理: {proxy}")
            if capabilities.proxy_config_available and ProxyConfig is not None:
                run_config_kwargs["proxy_config"] = ProxyConfig(server=proxy)
            else:
                run_config_kwargs["proxy_config"] = proxy
        elif use_proxy and not proxy:
            logger.warning("已启用代理但未配置地址，将不使用代理")

        run_config = CrawlerRunConfig(**run_config_kwargs)

        async with AsyncWebCrawler(config=browser_config) as crawler:
            result = await crawler.arun(url=url, config=run_config)

            if result.success:
                content = "# 网页解析结果\n\n"
                content += f"**URL**: {result.url}\n\n"

                if hasattr(result, "title") and result.title:
                    content += f"**标题**: {result.title}\n\n"

                if hasattr(result, "description") and result.description:
                    content += f"**描述**: {result.description}\n\n"

                content += "---\n\n## 内容\n\n"

                markdown_text = result.markdown or ""
                if max_chars > 0 and len(markdown_text) > max_chars:
                    markdown_text = markdown_text[:max_chars] + "\n\n...（内容已截断）"

                content += markdown_text
                return content
            else:
                error_msg = getattr(result, "error_message", "未知错误")
                logger.error(f"抓取失败: {error_msg}")
                return f"网页抓取失败: {error_msg}"

    except RuntimeError as e:
        install_hint = _resolve_playwright_install_hint(e)
        if install_hint is not None:
            logger.error(f"Playwright 浏览器缺失: {e}")
            return install_hint
        if "ERR_NETWORK_CHANGED" in str(e) or "ERR_CONNECTION" in str(e):
            logger.error(f"网络连接错误: {e}")
            return "网络连接错误，可能是代理配置问题。请检查代理设置或关闭代理。"
        else:
            logger.error(f"抓取网页时发生错误: {e}")
            return "抓取网页时发生错误，请稍后重试"
    except Exception as e:
        install_hint = _resolve_playwright_install_hint(e)
        if install_hint is not None:
            logger.error(f"Playwright 浏览器缺失: {e}")
            return install_hint
        logger.error(f"网页获取失败: {e}")
        return "网页获取失败，请稍后重试"
