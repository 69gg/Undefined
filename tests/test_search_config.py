from __future__ import annotations

from pathlib import Path

import pytest

from Undefined.config import Config
from Undefined.config.search import (
    SEARCH_TOOL_FIRECRAWL,
    SEARCH_TOOL_GROK,
    SEARCH_TOOL_SEARXNG,
)


_MINIMAL_MAPPING = {
    "onebot": {"ws_url": "ws://127.0.0.1:3001"},
    "models": {
        "chat": {"api_url": "u", "api_key": "k", "model_name": "chat"},
        "vision": {"api_url": "u", "api_key": "k", "model_name": "vision"},
        "agent": {"api_url": "u", "api_key": "k", "model_name": "agent"},
    },
}


def test_search_config_defaults() -> None:
    cfg = Config.from_mapping(_MINIMAL_MAPPING, strict=False)

    assert cfg.search_priority == [
        SEARCH_TOOL_GROK,
        SEARCH_TOOL_FIRECRAWL,
        SEARCH_TOOL_SEARXNG,
    ]
    assert cfg.firecrawl_search_enabled is False
    assert cfg.firecrawl_api_key == ""
    assert cfg.firecrawl_base_url == "https://api.firecrawl.dev"


def test_search_config_loads_firecrawl_and_priority(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[onebot]
ws_url = "ws://127.0.0.1:3001"

[models.chat]
api_url = "u"
api_key = "k"
model_name = "chat"

[models.vision]
api_url = "u"
api_key = "k"
model_name = "vision"

[models.agent]
api_url = "u"
api_key = "k"
model_name = "agent"

[search]
priority = ["web_search", "firecrawl_search", "web_search", "unknown"]
grok_search_enabled = true

[search.firecrawl]
enabled = true
api_key = "fc-test"
base_url = "https://firecrawl.internal/"
""",
        encoding="utf-8",
    )

    cfg = Config.load(config_path, strict=False)

    assert cfg.search_priority == [
        SEARCH_TOOL_SEARXNG,
        SEARCH_TOOL_FIRECRAWL,
        SEARCH_TOOL_GROK,
    ]
    assert cfg.grok_search_enabled is True
    assert cfg.firecrawl_search_enabled is True
    assert cfg.firecrawl_api_key == "fc-test"
    assert cfg.firecrawl_base_url == "https://firecrawl.internal"


def test_search_config_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "SEARCH_PRIORITY",
        "firecrawl_search,web_search,invalid,firecrawl_search",
    )
    monkeypatch.setenv("FIRECRAWL_SEARCH_ENABLED", "true")
    monkeypatch.setenv("FIRECRAWL_API_KEY", "fc-env")
    monkeypatch.setenv("FIRECRAWL_BASE_URL", "https://firecrawl.env")

    cfg = Config.from_mapping(_MINIMAL_MAPPING, strict=False)

    assert cfg.search_priority == [
        SEARCH_TOOL_FIRECRAWL,
        SEARCH_TOOL_SEARXNG,
        SEARCH_TOOL_GROK,
    ]
    assert cfg.firecrawl_search_enabled is True
    assert cfg.firecrawl_api_key == "fc-env"
    assert cfg.firecrawl_base_url == "https://firecrawl.env"
