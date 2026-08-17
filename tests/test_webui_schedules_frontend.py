"""Frontend contracts for the automations list / canvas pages."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Final

from Undefined.utils import io as async_io

SCHEDULES_JS: Final[Path] = Path("src/Undefined/webui/static/js/schedules.js")
GRAPH_JS: Final[Path] = Path("src/Undefined/webui/static/js/workflow-graph.js")
INSPECTOR_JS: Final[Path] = Path("src/Undefined/webui/static/js/workflow-inspector.js")
I18N_JS: Final[Path] = Path("src/Undefined/webui/static/js/i18n.js")


def _read_source(path: Path) -> str:
    text = asyncio.run(async_io.read_text(path))
    assert text is not None
    return text


def test_save_reloads_list_and_scrolls_to_list_page() -> None:
    source = _read_source(SCHEDULES_JS)
    save_fn = source.split("async function save()", 1)[1].split(
        "async function removeSelected()", 1
    )[0]
    refresh_fn = source.split("async function refresh(options = {})", 1)[1].split(
        "function maybeOpenFromQuery()", 1
    )[0]

    assert "if (scheduleState.busy && !force) return;" in refresh_fn
    assert "await refresh({ force: true, skipOpenFromQuery: true });" in save_fn
    assert 'showSchedulePage("list")' in save_fn


def test_blank_workflow_defaults_do_not_consume_or_auto_send() -> None:
    graph = _read_source(GRAPH_JS)
    inspector = _read_source(INSPECTOR_JS)
    i18n = _read_source(I18N_JS)
    empty_task = graph.split("function emptyTask()", 1)[1].split(
        "function defaultNode(", 1
    )[0]
    assert "consume_ai_loop: false" in empty_task
    assert "auto_send_final: false" in empty_task
    assert (
        'checkbox("consume_ai_loop", task.consume_ai_loop === true, "schedules.consume")'
        in inspector
    )
    assert (
        'checkbox("auto_send_final", task.auto_send_final === true, "schedules.auto_send")'
        in inspector
    )
    assert '"schedules.consume": "拦截主 AI"' in i18n
    assert "关闭则后台执行" not in i18n


def test_llm_inspector_supports_extract_vars() -> None:
    graph = _read_source(GRAPH_JS)
    inspector = _read_source(INSPECTOR_JS)
    i18n = _read_source(I18N_JS)
    blank_node = graph.split('if (type === "llm.blank")', 1)[1].split(
        'if (type === "llm.agent")', 1
    )[0]
    agent_node = graph.split('if (type === "llm.agent")', 1)[1].split(
        'if (type === "llm.main")', 1
    )[0]
    main_node = graph.split('if (type === "llm.main")', 1)[1].split(
        'if (type === "branch.if")', 1
    )[0]
    assert "extract_vars: []" in blank_node
    assert "extract_vars: []" in agent_node
    assert "extract_vars: []" in main_node
    assert "function extractVarLabel(node)" in graph
    assert "function extractVarsMarkup(node)" in inspector
    assert "function llmOutputMarkup(node)" in inspector
    assert "patch.extract_vars" in inspector
    assert "data-extract-add" in inspector
    assert "data-extract-remove" in inspector
    assert 'node.type === "llm.blank"' in inspector
    assert 'node.type === "llm.agent"' in inspector
    assert 'node.type === "llm.main"' in inspector
    assert 'node.type === "branch.llm"' in inspector
    assert '"schedules.extract_vars": "变量提取"' in i18n
    assert '"schedules.add_extract_var": "添加变量"' in i18n
    assert "extract_<名称>" in i18n
    assert '"schedules.extract_vars": "Extract variables"' in i18n
