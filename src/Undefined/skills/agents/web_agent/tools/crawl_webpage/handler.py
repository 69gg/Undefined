from typing import Any, Dict
import logging

from Undefined.config import get_config

logger = logging.getLogger(__name__)


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    """对指定网页进行抓取、渲染并提取其中的文本或特定元素内容"""
    url = args.get("url", "")
    if not url:
        return "URL 不能为空"

    # 从 context 标志检查可用性或尝试导入
    if not context.get("crawl4ai_available", False):
        return "网页获取功能未启用（crawl4ai 未安装）"

    try:
        from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig

        try:
            from crawl4ai import ProxyConfig

            _PROXY_CONFIG_AVAILABLE = True
        except ImportError:
            _PROXY_CONFIG_AVAILABLE = False

    except ImportError:
        return "网页获取功能未启用（crawl4ai 未安装）"

    max_chars = args.get("max_chars", 4096)

    try:
        runtime_config = get_config(strict=False)
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
            if _PROXY_CONFIG_AVAILABLE:
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
        if "ERR_NETWORK_CHANGED" in str(e) or "ERR_CONNECTION" in str(e):
            logger.error(f"网络连接错误: {e}")
            return (
                f"网络连接错误，可能是代理配置问题。请检查代理设置或关闭代理。错误: {e}"
            )
        else:
            logger.error(f"抓取网页时发生错误: {e}")
            return f"抓取网页时发生错误: {e}"
    except Exception as e:
        logger.error(f"网页获取失败: {e}")
        return f"网页获取失败: {e}"
