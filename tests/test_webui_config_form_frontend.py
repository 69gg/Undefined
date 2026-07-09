"""Static frontend contracts for WebUI config form (request_params / search)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Final

from Undefined.utils import io as async_io

CONFIG_FORM_JS: Final[Path] = Path("src/Undefined/webui/static/js/config-form.js")
COMPONENTS_CSS: Final[Path] = Path("src/Undefined/webui/static/css/components.css")


def _read_source(path: Path) -> str:
    text = asyncio.run(async_io.read_text(path))
    assert text is not None
    return text


def _has_bare_form_group_query(source: str) -> bool:
    """True if source still queries all .form-group nodes (not only [data-path])."""
    return 'querySelectorAll(".form-group")' in source or (
        'querySelector(\n                ".form-group:not(.is-hidden)",\n            )'
        in source
        or '".form-group:not(.is-hidden)"' in source
    )


def test_config_search_filters_only_path_bearing_form_groups() -> None:
    """Nested key/type form-groups inside request_params must not be filtered alone."""
    source = _read_source(CONFIG_FORM_JS)

    assert 'querySelectorAll(".form-group[data-path]")' in source
    assert ".form-group[data-path]:not(.is-hidden)" in source
    assert not _has_bare_form_group_query(source)


def test_config_search_index_only_targets_path_bearing_form_groups() -> None:
    source = _read_source(CONFIG_FORM_JS)
    index_fn = source.split("function updateConfigSearchIndex()", 1)[1].split(
        "function ", 1
    )[0]
    assert 'querySelectorAll(".form-group[data-path]")' in index_fn
    assert 'querySelectorAll(".form-group")' not in index_fn


def test_apply_config_filter_only_targets_path_bearing_form_groups() -> None:
    source = _read_source(CONFIG_FORM_JS)
    filter_fn = source.split("function applyConfigFilter()", 1)[1].split(
        "function ", 1
    )[0]
    assert 'querySelectorAll(".form-group[data-path]")' in filter_fn
    assert ".form-group[data-path]:not(.is-hidden)" in filter_fn
    assert 'querySelectorAll(".form-group")' not in filter_fn
    assert '".form-group:not(.is-hidden)"' not in filter_fn


def test_request_params_widget_contracts() -> None:
    source = _read_source(CONFIG_FORM_JS)
    css = _read_source(COMPONENTS_CSS)

    assert "function isRequestParamsPath(path)" in source
    assert 'path.endsWith(".request_params")' in source
    assert "function createRequestParamsWidget(path, value)" in source
    assert 'editor.dataset.requestParamsRoot = "true"' in source
    assert "config-request-params" in source
    assert ".form-group.config-request-params" in css
    assert "grid-column: 1 / -1" in css
