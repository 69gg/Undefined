"""Shared Crawl4AI capability helpers.

`crawl4ai` 是必需依赖（声明在 `pyproject.toml`），这里不再做“未安装则降级”的
探测：导入失败会直接抛错。保留下来的只有版本能力差异（如部分版本没有
`ProxyConfig`），它决定是否能把代理配置传给 crawler。
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

_REQUIRED_ATTRIBUTES = ("AsyncWebCrawler", "BrowserConfig", "CrawlerRunConfig")


@dataclass(frozen=True, slots=True)
class Crawl4AICapabilities:
    """Resolved Crawl4AI runtime capabilities."""

    proxy_config_available: bool
    async_web_crawler: Any
    browser_config: Any
    crawler_run_config: Any
    proxy_config: Any = None


@lru_cache(maxsize=1)
def get_crawl4ai_capabilities() -> Crawl4AICapabilities:
    """读取 Crawl4AI 运行时能力；缺少必需类时抛 RuntimeError。"""

    module = importlib.import_module("crawl4ai")
    missing = [name for name in _REQUIRED_ATTRIBUTES if not hasattr(module, name)]
    if missing:
        raise RuntimeError(
            "已安装的 crawl4ai 缺少必需接口: "
            + ", ".join(missing)
            + "；请升级 crawl4ai 到受支持的版本"
        )

    proxy_config = getattr(module, "ProxyConfig", None)
    return Crawl4AICapabilities(
        proxy_config_available=proxy_config is not None,
        async_web_crawler=module.AsyncWebCrawler,
        browser_config=module.BrowserConfig,
        crawler_run_config=module.CrawlerRunConfig,
        proxy_config=proxy_config,
    )


def reset_crawl4ai_capabilities_cache() -> None:
    """Clear the cached Crawl4AI capability probe."""

    get_crawl4ai_capabilities.cache_clear()
