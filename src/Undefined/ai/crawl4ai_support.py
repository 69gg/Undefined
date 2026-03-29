"""Shared Crawl4AI capability detection helpers."""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from functools import lru_cache
from typing import Any


@dataclass(frozen=True, slots=True)
class Crawl4AICapabilities:
    """Resolved Crawl4AI runtime capabilities."""

    available: bool
    proxy_config_available: bool
    async_web_crawler: Any = None
    browser_config: Any = None
    crawler_run_config: Any = None
    proxy_config: Any = None
    error: str | None = None


@lru_cache(maxsize=1)
def get_crawl4ai_capabilities() -> Crawl4AICapabilities:
    """Detect whether Crawl4AI core classes are importable."""

    try:
        module = importlib.import_module("crawl4ai")
        async_web_crawler = getattr(module, "AsyncWebCrawler")
        browser_config = getattr(module, "BrowserConfig")
        crawler_run_config = getattr(module, "CrawlerRunConfig")
    except Exception as exc:
        return Crawl4AICapabilities(
            available=False,
            proxy_config_available=False,
            error=f"{type(exc).__name__}: {exc}",
        )

    proxy_config = getattr(module, "ProxyConfig", None)
    return Crawl4AICapabilities(
        available=True,
        proxy_config_available=proxy_config is not None,
        async_web_crawler=async_web_crawler,
        browser_config=browser_config,
        crawler_run_config=crawler_run_config,
        proxy_config=proxy_config,
    )


def reset_crawl4ai_capabilities_cache() -> None:
    """Clear the cached Crawl4AI capability probe."""

    get_crawl4ai_capabilities.cache_clear()
