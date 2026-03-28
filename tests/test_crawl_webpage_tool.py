from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from Undefined.ai.crawl4ai_support import Crawl4AICapabilities
from Undefined.skills.agents.web_agent.tools.crawl_webpage import (
    handler as crawl_handler,
)


class _FakeBrowserConfig:
    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs


class _FakeCrawlerRunConfig:
    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs


class _FakeCrawler:
    def __init__(
        self,
        *,
        config: _FakeBrowserConfig,
        result: Any,
        enter_error: BaseException | None = None,
    ) -> None:
        self.config = config
        self._result = result
        self._enter_error = enter_error
        self.calls: list[dict[str, Any]] = []

    async def __aenter__(self) -> _FakeCrawler:
        if self._enter_error is not None:
            raise self._enter_error
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: Any,
    ) -> None:
        return None

    async def arun(self, *, url: str, config: _FakeCrawlerRunConfig) -> Any:
        self.calls.append({"url": url, "config": config})
        return self._result


def _runtime_config() -> SimpleNamespace:
    return SimpleNamespace(use_proxy=False, http_proxy=None, https_proxy=None)


def _successful_capabilities(
    crawler_factory: Any,
) -> Crawl4AICapabilities:
    return Crawl4AICapabilities(
        available=True,
        proxy_config_available=False,
        async_web_crawler=crawler_factory,
        browser_config=_FakeBrowserConfig,
        crawler_run_config=_FakeCrawlerRunConfig,
    )


@pytest.mark.asyncio
async def test_crawl_webpage_ignores_missing_context_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result_payload = SimpleNamespace(
        success=True,
        url="https://example.com",
        title="Example Title",
        description="Example Description",
        markdown="Example body",
    )

    def _crawler_factory(*, config: _FakeBrowserConfig) -> _FakeCrawler:
        return _FakeCrawler(config=config, result=result_payload)

    monkeypatch.setattr(
        crawl_handler,
        "get_crawl4ai_capabilities",
        lambda: _successful_capabilities(_crawler_factory),
    )

    result = await crawl_handler.execute(
        {"url": "https://example.com"},
        {"runtime_config": _runtime_config()},
    )

    assert "# 网页解析结果" in result
    assert "**标题**: Example Title" in result
    assert "Example body" in result


@pytest.mark.asyncio
async def test_crawl_webpage_ignores_stale_false_context_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result_payload = SimpleNamespace(
        success=True,
        url="https://example.com",
        title=None,
        description=None,
        markdown="A" * 32,
    )

    def _crawler_factory(*, config: _FakeBrowserConfig) -> _FakeCrawler:
        return _FakeCrawler(config=config, result=result_payload)

    monkeypatch.setattr(
        crawl_handler,
        "get_crawl4ai_capabilities",
        lambda: _successful_capabilities(_crawler_factory),
    )

    result = await crawl_handler.execute(
        {"url": "https://example.com", "max_chars": 8},
        {
            "runtime_config": _runtime_config(),
            "crawl4ai_available": False,
        },
    )

    assert "网页获取功能未启用" not in result
    assert "...（内容已截断）" in result


@pytest.mark.asyncio
async def test_crawl_webpage_returns_unavailable_when_core_import_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        crawl_handler,
        "get_crawl4ai_capabilities",
        lambda: Crawl4AICapabilities(
            available=False,
            proxy_config_available=False,
            error="ImportError: No module named crawl4ai",
        ),
    )

    result = await crawl_handler.execute({"url": "https://example.com"}, {})

    assert result == "网页获取功能未启用（crawl4ai 未安装）"


@pytest.mark.asyncio
async def test_crawl_webpage_returns_playwright_install_hint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    browser_error = RuntimeError(
        "BrowserType.launch: Executable doesn't exist\n"
        "Please run the following command to download new browsers:\n"
        "playwright install"
    )

    def _crawler_factory(*, config: _FakeBrowserConfig) -> _FakeCrawler:
        return _FakeCrawler(
            config=config,
            result=None,
            enter_error=browser_error,
        )

    monkeypatch.setattr(
        crawl_handler,
        "get_crawl4ai_capabilities",
        lambda: _successful_capabilities(_crawler_factory),
    )

    result = await crawl_handler.execute(
        {"url": "https://example.com"},
        {"runtime_config": _runtime_config()},
    )

    assert "uv run playwright install" in result
